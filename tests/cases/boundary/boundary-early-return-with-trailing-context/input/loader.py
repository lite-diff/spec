import os

def load(path):
    if path:
        data = read(path)
        return data
    else:
        data = None
        return data

def save(data):
    write(data)
