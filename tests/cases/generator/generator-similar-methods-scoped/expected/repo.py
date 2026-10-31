class Repo:
    def load(self):
        self._check()
        return self._data

    def save(self):
        self._check()
        self._flush()
        return self._data

    def size(self):
        return len(self._data)
