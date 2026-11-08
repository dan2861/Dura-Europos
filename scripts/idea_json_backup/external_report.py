"""Exclusive report publication outside protected evidence directories."""
from contextlib import ExitStack
import os
from pathlib import Path
import uuid

from scripts.sample_backup import jsoncodec as codec

from .files import describe
from .package import _Parent, _Output, _write, _publish, _output_hash


class _ReportDirectory(_Output):
    def __init__(self, path, parent):
        self.path = self.target = path
        self.fd = os.dup(parent.fd)
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise


class ExternalReport:
    """Enter before auditing; keep the chosen report parent anchored throughout."""
    def __init__(self, path, *, protected_roots):
        self.requested = Path(path).absolute()
        self.protected = tuple(Path(root).absolute() for root in protected_roots)
        self._stack = None
        self._directory = None

    def __enter__(self):
        self._stack = ExitStack()
        try:
            self.target = self.requested.parent.resolve(strict=True) / self.requested.name
            self._protected_anchors = tuple(path.resolve() for path in self.protected)
            self._check_scope()
            parent = self._stack.enter_context(_Parent(self.target.parent))
            self._directory = self._stack.enter_context(_ReportDirectory(self.target.parent, parent))
            self._check()
            self._absent()
            return self
        except BaseException as exc:
            self._stack.close()
            self._directory = None
            if isinstance(exc, RuntimeError):
                raise ValueError("Unsafe external report path") from exc
            raise

    def _check_scope(self):
        current = tuple(path.resolve() for path in self.protected)
        if any(self.target.is_relative_to(root) for root in self._protected_anchors + current):
            raise ValueError("Report must be outside package and downloaded evidence")
        if any(self.requested.is_relative_to(root) for root in self.protected):
            raise ValueError("Report must be outside protected input paths")

    def _check(self):
        self._check_scope()
        if self.requested.parent.resolve(strict=True) != self.target.parent:
            raise ValueError("External report ancestry changed")
        self._directory.check()

    def _absent(self):
        try:
            os.stat(self.target.name, dir_fd=self._directory.fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError("External report destination already exists")

    def write(self, report, *, validate=None):
        if self._directory is None:
            raise ValueError("External report context is not open")
        try:
            self._check()
            self._absent()
            if validate is not None:
                validate()
            body = (codec.dumps(report) + "\n").encode("utf-8")
            pending = f".{self.target.name}.{uuid.uuid4().hex}.pending"
            _write(self._directory, pending, body)
            self._check()
            if validate is not None:
                validate()
            _publish(self._directory, pending, self.target.name)
            self._check()
            if validate is not None:
                validate()
            actual = _output_hash(self._directory, self.target.name)
            if actual != describe(self.target.name, body):
                raise ValueError("Published external report bytes changed")
            return actual
        except RuntimeError as exc:
            raise ValueError("Unsafe external report path") from exc

    def __exit__(self, *args):
        self._stack.close()
        self._directory = None
