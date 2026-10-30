"""Guarded business tools. Model output is never an authority for business state."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('slot must be a string')
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('slots must be timezone-aware full hours')
    normalized = dt.astimezone(timezone(timedelta(hours=8)))
    if normalized.minute or normalized.second or normalized.microsecond:
        raise ValueError('slots must be full hours in Asia/Shanghai')
    return normalized.isoformat()


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError('request must be an object')
    for key in ('request_id', 'material_id', 'channel'):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ValueError(f'{key} must be a nonempty string')
    if type(request.get('hard_time')) is not bool:
        raise ValueError('hard_time must be boolean')
    request['requested_slot'] = timestamp(request['requested_slot'])
    slots = request.get('candidate_slots', [])
    approved = request.get('approved_slots', [])
    if not isinstance(slots, list) or not isinstance(approved, list):
        raise ValueError('candidate_slots and approved_slots must be lists')
    request['candidate_slots'] = list(dict.fromkeys([request['requested_slot']] + [timestamp(s) for s in slots]))
    request['approved_slots'] = [timestamp(s) for s in approved]
    if not set(request['approved_slots']).issubset(request['candidate_slots']):
        raise ValueError('approved slots must belong to candidate slots')
    return request


class Tools:
    def __init__(self, request, data, database, fail_save=False):
        self.request = validate_request(dict(request))
        self.data = data
        self.fail_save = fail_save
        self.material = None
        self.review = None
        self.slot_result = None
        self.saved = None
        self.last_error = None
        self.db = sqlite3.connect(str(database), timeout=5)
        self.db.execute('''CREATE TABLE IF NOT EXISTS drafts (
            draft_id INTEGER PRIMARY KEY, business_key TEXT UNIQUE NOT NULL,
            fingerprint TEXT NOT NULL, channel TEXT NOT NULL, slot TEXT NOT NULL,
            payload TEXT NOT NULL, UNIQUE(channel, slot))''')
        self.db.commit()

    def close(self):
        self.db.close()

    @property
    def key(self):
        return self.request['request_id'] + ':' + self.request['material_id']

    @property
    def fingerprint(self):
        raw = json.dumps(self.request, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def execute(self, name, args):
        allowed = {
            'read_material': set(), 'lookup_metadata': set(), 'check_rules': set(),
            'query_slots': set(), 'save_draft': {'slot'},
        }
        if name not in allowed or not isinstance(args, dict) or set(args) != allowed[name]:
            return {'ok': False, 'error': 'invalid_tool_or_arguments'}
        try:
            result = getattr(self, name)(**args)
        except (sqlite3.Error, OSError):
            result = {'ok': False, 'error': 'storage_error'}
        except (ValueError, TypeError):
            result = {'ok': False, 'error': 'invalid_arguments'}
        if not result.get('ok'):
            self.last_error = result.get('error')
        return result

    def read_material(self):
        material = self.data['materials'].get(self.request['material_id'])
        if material is None:
            return {'ok': False, 'error': 'material_not_found'}
        self.material = dict(material)
        self.review = None
        return {'ok': True, 'material': self.material}

    def lookup_metadata(self):
        if self.material is None:
            return {'ok': False, 'error': 'read_material_first'}
        extra = self.data.get('supplements', {}).get(self.request['material_id'], {})
        # Supplement only missing fields; it cannot erase risk-bearing content.
        for key, value in extra.items():
            if not self.material.get(key):
                self.material[key] = value
        self.review = None
        return {'ok': True, 'found': bool(extra), 'material': self.material}

    def check_rules(self):
        if self.material is None:
            return {'ok': False, 'error': 'read_material_first'}
        missing = [k for k in self.data['rules']['required_fields'] if not self.material.get(k)]
        text = str(self.material.get('text', ''))
        risks = ['forbidden:' + term for term in self.data['rules']['forbidden_terms'] if term in text]
        if self.material.get('rights') and self.material['rights'] != 'cleared':
            risks.append('rights_not_cleared')
        self.review = {'status': 'blocked' if risks else 'needs_information' if missing else 'approved',
                       'risks': risks, 'missing': missing}
        return {'ok': True, **self.review}

    def occupied(self):
        occupied = {timestamp(x['slot']) for x in self.data.get('occupied', [])
                    if x['channel'] == self.request['channel']}
        rows = self.db.execute('SELECT slot FROM drafts WHERE channel=? AND business_key<>?',
                               (self.request['channel'], self.key)).fetchall()
        return occupied | {row[0] for row in rows}

    def query_slots(self):
        busy = self.occupied()
        slots = self.request['candidate_slots']
        self.slot_result = {'ok': True, 'available': [s for s in slots if s not in busy],
                            'occupied': [s for s in slots if s in busy]}
        return self.slot_result

    def save_draft(self, slot):
        slot = timestamp(slot)
        if not self.review or self.review['status'] != 'approved':
            return {'ok': False, 'error': 'review_not_approved'}
        if not self.slot_result or slot not in self.slot_result['available']:
            return {'ok': False, 'error': 'slot_not_checked_or_unavailable'}
        if slot not in self.request['candidate_slots']:
            return {'ok': False, 'error': 'slot_outside_candidates'}
        # Pending draft is a proposal, never an authorized change or publication.
        pending = (self.request['hard_time'] and slot != self.request['requested_slot']
                   and slot not in self.request['approved_slots'])
        payload = {'material_id': self.request['material_id'], 'channel': self.request['channel'],
                   'requested_slot': self.request['requested_slot'], 'suggested_slot': slot,
                   'confirmation_status': 'pending' if pending else 'not_required',
                   'pending_items': ['confirm_hard_time_change'] if pending else [],
                   'publication_status': 'not_published'}
        if self.fail_save:
            return {'ok': False, 'error': 'save_failed_injected'}
        try:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT draft_id,fingerprint,payload FROM drafts WHERE business_key=?',
                                       (self.key,)).fetchone()
            if existing:
                self.db.rollback()
                if existing[1] != self.fingerprint:
                    return {'ok': False, 'error': 'idempotency_key_reused_with_changed_request'}
                self.saved = {'draft_id': existing[0], **json.loads(existing[2]), 'save_status': 'existing'}
                return {'ok': True, **self.saved}
            if slot in self.occupied():
                self.db.rollback()
                return {'ok': False, 'error': 'slot_conflict_at_save'}
            cursor = self.db.execute('INSERT INTO drafts(business_key,fingerprint,channel,slot,payload) VALUES(?,?,?,?,?)',
                                     (self.key, self.fingerprint, self.request['channel'], slot,
                                      json.dumps(payload, ensure_ascii=False)))
            self.db.commit()
            self.saved = {'draft_id': cursor.lastrowid, **payload, 'save_status': 'saved'}
            return {'ok': True, **self.saved}
        except Exception:
            self.db.rollback()
            raise

    def report(self, status, reason):
        saved = self.saved or {}
        save_failed = bool(self.last_error and ('save' in self.last_error or self.last_error == 'storage_error'))
        return {'material_id': self.request['material_id'], 'status': status, 'reason': reason,
                'review': self.review or {'status': 'not_checked', 'risks': [], 'missing': []},
                'requested_slot': self.request['requested_slot'],
                'suggested_slot': saved.get('suggested_slot'),
                'pending_items': saved.get('pending_items', (self.review or {}).get('missing', [])),
                'confirmation_status': saved.get('confirmation_status', 'not_applicable'),
                'save_status': saved.get('save_status', 'failed' if save_failed else 'not_saved'),
                'draft_id': saved.get('draft_id'), 'publication_status': 'not_published'}
