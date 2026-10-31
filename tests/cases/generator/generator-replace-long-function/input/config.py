import json

def parse_config(path):
    """Parse the config file."""
    result = {}
    with open(path) as fh:
        text = fh.read()
    if not text.strip():
        return result
    data = json.loads(text)
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            value = value.strip()
        result[key] = value
    if "name" not in result:
        result["name"] = "default"
    if "version" not in result:
        result["version"] = 1
    if "debug" in result:
        result["debug"] = bool(result["debug"])
    for required in ("name", "version"):
        if required not in result:
            raise KeyError(required)
    validate(result)
    return result

def validate(cfg):
    return bool(cfg)
