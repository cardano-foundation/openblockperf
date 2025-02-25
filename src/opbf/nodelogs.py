import abc
import os
import systemd.journal


class NodeLogReader(abc.ABC):
    """
    Abstract Base Class for log readers.
    """

    @abc.abstractmethod
    def read_logs(self):
        pass


class FileLogReader(NodeLogReader):
    """
    Reads logs from a specified file.
    """

    def __init__(self, file_path):
        self.file_path = file_path

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Log file {file_path} does not exist.")

    def read_logs(self):
        with open(self.file_path, "r") as file:
            for line in file:
                yield line.strip()


class JournaldLogReader(NodeLogReader):
    """
    Reads logs from the systemd journal.
    """

    def __init__(self, unit=None):
        self.journal = systemd.journal.Reader()
        if unit:
            self.journal.add_match(_SYSTEMD_UNIT=unit)
        self.journal.seek_tail()

    def read_logs(self):
        self.journal.seek_tail()
        self.journal.get_previous()
        while True:
            entry = self.journal.get_next()
            if entry is None:
                break
            yield entry.get("MESSAGE", "")


def create_log_reader(source_type, source):
    if source_type == "file":
        return FileLogReader(source)
    elif source_type == "journald":
        return JournaldLogReader(unit=source)
    else:
        raise ValueError("Unsupported log source type. Use 'file' or 'journald'.")
