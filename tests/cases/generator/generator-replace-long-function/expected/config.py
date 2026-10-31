import json

def parse_config(path):
    """Parse the config file."""
    with open(path) as fh:
        data = json.load(fh)
    validate(data)
    return data

def validate(cfg):
    return bool(cfg)
