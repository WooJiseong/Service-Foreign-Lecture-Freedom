"""Server-only configuration; validation diagnostics never contain values."""
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import yaml

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env', override=False)
LIMITS = {
    'max_bytes': ('FLF_MAX_BYTES', 104857600),
    'max_seconds': ('FLF_MAX_SECONDS', 7200),
    'max_jobs': ('FLF_MAX_JOBS', 50),
    'max_queue': ('FLF_MAX_QUEUE', 20),
    'max_storage': ('FLF_MAX_STORAGE', 2147483648),
    'max_db_bytes': ('FLF_MAX_DB_BYTES', 67108864),
    'max_validations': ('FLF_MAX_VALIDATIONS', 2),
    'lease_seconds': ('FLF_LEASE_SECONDS', 180),
    'heartbeat_seconds': ('FLF_HEARTBEAT_SECONDS', 30),
    'max_calls': ('FLF_MAX_CALLS', 200),
    'max_chat_requests': ('FLF_MAX_CHAT_REQUESTS', 20),
    'reaper_milliseconds': ('FLF_REAPER_MILLISECONDS', 500),
    'cleanup_milliseconds': ('FLF_CLEANUP_MILLISECONDS', 500),
    'max_provider_response_bytes': ('FLF_MAX_PROVIDER_RESPONSE_BYTES', 8388608),
    'speech_wait_seconds': ('FLF_SPEECH_WAIT_SECONDS', 7200),
}
BOUNDS = {
    'max_bytes': (1024, 512 * 1024**2), 'max_seconds': (1, 14400),
    'max_jobs': (1, 200), 'max_queue': (1, 100),
    'max_storage': (1024**2, 20 * 1024**3), 'max_db_bytes': (65536, 512 * 1024**2),
    'max_validations': (1, 4), 'lease_seconds': (30, 3600),
    'heartbeat_seconds': (5, 120), 'max_calls': (1, 1000), 'max_chat_requests': (1, 100),
    'reaper_milliseconds': (100, 5000), 'cleanup_milliseconds': (100, 5000),
    'max_provider_response_bytes': (65536, 16 * 1024**2), 'speech_wait_seconds': (30, 14400),
}
REQUIRED = ('CLOVA_SPEECH_SECRET_KEY', 'CLOVA_SPEECH_INVOKE_URL',
            'PAPAGO_CLIENT_ID', 'PAPAGO_CLIENT_SECRET', 'CLOVASTUDIO_API_KEY',
            'NCLOUD_ACCESS_KEY_ID', 'NCLOUD_SECRET_KEY', 'NCLOUD_OBJECT_STORAGE_BUCKET',
            'NCLOUD_OBJECT_STORAGE_ENDPOINT', 'NCLOUD_OBJECT_STORAGE_INPUT_PREFIX',
            'NCLOUD_OBJECT_STORAGE_OUTPUT_PREFIX')


def load_config(path=None):
    path = Path(path or os.getenv('FLF_CONFIG', str(BASE / 'service.yaml')))
    if not path.is_absolute():
        path = BASE / path
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        raise ValueError('Invalid service.yaml') from None
    if not isinstance(raw, dict) or set(raw) - {'models', 'limits'}:
        raise ValueError('Invalid service.yaml schema')
    models, limits = raw.get('models', {}), raw.get('limits', {})
    if not isinstance(models, dict) or set(models) - {'summary', 'chat'}:
        raise ValueError('Invalid models schema')
    if not isinstance(limits, dict) or set(limits) - LIMITS.keys():
        raise ValueError('Invalid limits schema')
    result = {'models': {}, 'limits': {}}
    for role in ('summary', 'chat'):
        model = models.get(role)
        if model is None:
            model = os.getenv('CLOVASTUDIO_MODEL') or 'HCX-005'
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', model):
            raise ValueError('Invalid models.' + role)
        result['models'][role] = model
    for name, (env, default) in LIMITS.items():
        value = os.getenv(env, limits.get(name, default))
        if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
            raise ValueError('Invalid limit: ' + name)
        result['limits'][name] = int(value)
        if not BOUNDS[name][0] <= int(value) <= BOUNDS[name][1]:
            raise ValueError('Out of safe range: ' + name)
    if result['limits']['heartbeat_seconds'] * 2 >= result['limits']['lease_seconds']:
        raise ValueError('heartbeat_seconds must be less than half lease_seconds')
    values = result['limits']
    if not values['max_validations'] <= values['max_queue'] <= values['max_jobs']:
        raise ValueError('Require max_validations <= max_queue <= max_jobs')
    if values['max_storage'] < values['max_db_bytes'] + values['max_validations'] * (2*values['max_bytes'] + 1024**2):
        raise ValueError('max_storage must cover DB and concurrent upload/spool reservations')
    if values['speech_wait_seconds'] < values['max_seconds']:
        raise ValueError('speech_wait_seconds must cover max_seconds')
    return result


CONFIG = load_config()


def limit(name):
    return int(os.getenv(LIMITS[name][0], CONFIG['limits'][name]))
