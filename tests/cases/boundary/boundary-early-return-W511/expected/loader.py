import os

def load(path):
    return read(path) if path else None
    else:
        data = None
        return data

def save(data):
    write(data)
