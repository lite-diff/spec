import os

def load(path):
    return read(path) if path else None

def save(data):
    write(data)
