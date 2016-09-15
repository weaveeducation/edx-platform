import json
import hashlib


def additional_profile_fields_hash(fields_json):
    fields_str = json.dumps(fields_json, sort_keys=True)
    return hashlib.md5(fields_str).hexdigest()
