"""Ordinary local files for prompt records and registered PNG outputs."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from gda_assets.adapters.file_copy import copy_with_sha256
from gda_assets.adapters.files import validate_format
from gda_assets.application.ports import PortFailure
from gda_assets.domain.prompt import (
    JsonScalar,
    PromptFile,
    PromptOutput,
    PromptOutputRequest,
    PromptRecord,
)


_TEXT_LIMIT = 1024 * 1024
_JSON_LIMIT = 4 * 1024 * 1024
_PNG_LIMIT = 256 * 1024 * 1024
_OUTPUT_LIMIT = 64
_RECORD = TypeAdapter(PromptRecord)
_OUTPUT = TypeAdapter(PromptOutput)
_FILE = TypeAdapter(PromptFile)


def _identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def _safe_name(name: str) -> str:
    if (
        not name
        or name != Path(name).name
        or Path(name).suffix.lower() != ".png"
        or any(char in name for char in ("/", "\\", "\x00"))
    ):
        raise PortFailure("invalid_prompt", "Output name must be one PNG filename")
    return name


def _regular_input(path: Path, limit: int) -> os.stat_result:
    observed = path.stat()
    if not stat.S_ISREG(observed.st_mode) or observed.st_size > limit:
        raise ValueError("input is not a bounded regular file")
    return observed


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        before_path = _regular_input(path, limit)
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("input is not a bounded regular file")
            value = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = path.stat()
        if (
            len(value) > limit
            or _identity(before_path) != _identity(before)
            or _identity(before) != _identity(after)
            or _identity(after) != _identity(current)
        ):
            raise ValueError("input changed or exceeded its size limit")
        return value
    except (OSError, ValueError) as exc:
        raise PortFailure(
            "invalid_prompt", f"Invalid prompt input {path}: {exc}"
        ) from exc


def _png_facts(declared: Path, saved: Path) -> PromptFile:
    try:
        validate_format(saved)
        from PIL import Image

        with Image.open(saved) as image:
            width, height = image.size
        with saved.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = saved.stat().st_size
        return PromptFile(str(declared), saved, digest, size, width, height)
    except PortFailure as exc:
        raise PortFailure("invalid_prompt", str(exc)) from exc


def _relative_file(item: PromptFile | None, root: Path) -> dict | None:
    if item is None:
        return None
    value = _FILE.dump_python(item, mode="json")
    value["path"] = str(item.path.relative_to(root))
    return value


def _record_json(record: PromptRecord) -> bytes:
    root = record.record
    value = _RECORD.dump_python(record, mode="json")
    value["record"] = "."
    value["resolved_path"] = str(record.resolved_path.relative_to(root))
    value["template"] = _relative_file(record.template, root)
    value["style"] = _relative_file(record.style, root)
    value["references"] = [_relative_file(item, root) for item in record.references]
    value["outputs"] = []
    return json.dumps(value, indent=2, sort_keys=True).encode()


def _dump(record: PromptRecord, path: Path) -> None:
    value = _record_json(record)
    if len(value) > _JSON_LIMIT:
        raise PortFailure("invalid_prompt", "Prompt record exceeds its JSON limit")
    temporary = path.with_name(".record.json.tmp")
    temporary.write_bytes(value + b"\n")
    os.replace(temporary, path)


class PromptFiles:
    def read_text(self, path: Path) -> str:
        try:
            return _read_bounded(path.resolve(strict=True), _TEXT_LIMIT).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PortFailure(
                "invalid_prompt", f"Invalid prompt text {path}: {exc}"
            ) from exc

    def create(
        self,
        record: Path,
        *,
        mode: Literal["plain", "template"],
        authored_text: str | None,
        template: Path | None,
        template_content: str | None,
        style: Path | None,
        style_content: str | None,
        variables: dict[str, str],
        resolved_prompt: str,
        references: tuple[Path, ...],
        producer: str | None,
        requested_options: dict[str, JsonScalar],
        revised_from: str | None = None,
    ) -> PromptRecord:
        root = record.absolute()
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise PortFailure(
                "destination_conflict",
                f"Prompt record destination exists or cannot be created: {root}",
            ) from exc
        try:
            inputs = root / "inputs"
            inputs.mkdir()
            resolved_path = root / "resolved-prompt.txt"
            resolved_bytes = resolved_prompt.encode("utf-8")
            resolved_path.write_bytes(resolved_bytes)
            resolved_sha = hashlib.sha256(resolved_bytes).hexdigest()
            template_fact = (
                self._save_text(template, template_content, inputs / "template.txt")
                if template
                else None
            )
            style_fact = (
                self._save_text(style, style_content, inputs / "style.txt")
                if style
                else None
            )
            reference_dir = inputs / "references"
            reference_dir.mkdir()
            reference_facts = []
            for index, source in enumerate(references):
                try:
                    source = source.resolve(strict=True)
                except OSError as exc:
                    raise PortFailure(
                        "invalid_prompt", f"Prompt reference is unavailable: {source}"
                    ) from exc
                if source.suffix.lower() != ".png":
                    raise PortFailure(
                        "invalid_prompt", "Prompt references must be PNG files"
                    )
                target = reference_dir / f"{index:03d}-{source.name}"
                copy_with_sha256(source, target, max_bytes=_PNG_LIMIT)
                reference_facts.append(_png_facts(source, target))
            result = PromptRecord(
                1,
                root,
                mode,
                authored_text,
                template_fact,
                style_fact,
                dict(variables),
                resolved_prompt,
                resolved_path,
                resolved_sha,
                tuple(reference_facts),
                producer,
                dict(requested_options),
                revised_from=revised_from,
            )
            _dump(result, root / "record.json")
            return result
        except (OSError, PortFailure) as exc:
            shutil.rmtree(root, ignore_errors=True)
            if isinstance(exc, PortFailure):
                raise
            raise PortFailure(
                "prompt_stage_failed", f"Could not prepare prompt record: {exc}"
            ) from exc

    def _save_text(
        self, source: Path, content: str | None, destination: Path
    ) -> PromptFile:
        if content is None:
            raise PortFailure("invalid_prompt", "Saved prompt text is unavailable")
        encoded = content.encode()
        if len(encoded) > _TEXT_LIMIT:
            raise PortFailure(
                "invalid_prompt", "Saved prompt text exceeds its size limit"
            )
        destination.write_bytes(encoded)
        return PromptFile(
            str(source), destination, hashlib.sha256(encoded).hexdigest(), len(encoded)
        )

    def read(self, record: Path) -> PromptRecord:
        try:
            root = record.resolve(strict=True)
            result = _RECORD.validate_json(
                _read_bounded(root / "record.json", _JSON_LIMIT), strict=True
            )
            result = self._rebase(result, root)
            outputs = []
            output_dir = root / "outputs"
            if output_dir.exists():
                if not output_dir.is_dir() or not output_dir.resolve().is_relative_to(
                    root
                ):
                    raise ValueError("Prompt output directory is invalid")
                registrations = sorted(output_dir.glob("*.json"))
                if len(registrations) > _OUTPUT_LIMIT:
                    raise ValueError("Prompt record has too many output registrations")
                for registration in registrations:
                    output = _OUTPUT.validate_json(
                        _read_bounded(registration, _JSON_LIMIT), strict=True
                    )
                    file = self._rebase_file(output.file, root)
                    assert file is not None
                    outputs.append(PromptOutput(**{**output.__dict__, "file": file}))
            result = PromptRecord(**{**result.__dict__, "outputs": tuple(outputs)})
            self._verify(result)
            return result
        except (OSError, ValidationError, TypeError, ValueError, PortFailure) as exc:
            if isinstance(exc, PortFailure) and exc.code == "invalid_prompt":
                raise
            raise PortFailure(
                "invalid_prompt", f"Invalid prompt record {record}: {exc}"
            ) from exc

    @staticmethod
    def _rebase_file(item: PromptFile | None, root: Path) -> PromptFile | None:
        if item is None:
            return None
        path = item.path if item.path.is_absolute() else root / item.path
        return PromptFile(**{**item.__dict__, "path": path})

    def _rebase(self, record: PromptRecord, root: Path) -> PromptRecord:
        resolved = (
            record.resolved_path
            if record.resolved_path.is_absolute()
            else root / record.resolved_path
        )
        return PromptRecord(
            **{
                **record.__dict__,
                "record": root,
                "resolved_path": resolved,
                "template": self._rebase_file(record.template, root),
                "style": self._rebase_file(record.style, root),
                "references": tuple(
                    PromptFile(**{**item.__dict__, "path": root / item.path})
                    if not item.path.is_absolute()
                    else item
                    for item in record.references
                ),
            }
        )

    def _verify(self, record: PromptRecord) -> None:
        files = [item for item in (record.template, record.style) if item]
        files.extend(record.references)
        files.extend(output.file for output in record.outputs)
        for item in files:
            if (
                not item.path.resolve().is_relative_to(record.record)
                or not item.path.is_file()
            ):
                raise ValueError("Prompt record contains an unavailable saved file")
            data = _read_bounded(
                item.path, _PNG_LIMIT if item.width is not None else _TEXT_LIMIT
            )
            if (
                len(data) != item.size_bytes
                or hashlib.sha256(data).hexdigest() != item.sha256
            ):
                raise ValueError("Prompt record saved input or output changed")
        if not record.resolved_path.resolve().is_relative_to(record.record):
            raise ValueError("Prompt record resolved text escapes its directory")
        resolved = _read_bounded(record.resolved_path, _TEXT_LIMIT)
        if (
            resolved.decode() != record.resolved_prompt
            or hashlib.sha256(resolved).hexdigest() != record.resolved_sha256
        ):
            raise ValueError("Prompt record resolved text changed")

    def add_output(
        self, record: PromptRecord, request: PromptOutputRequest
    ) -> PromptRecord:
        if len(record.outputs) >= _OUTPUT_LIMIT:
            raise PortFailure(
                "invalid_prompt",
                f"A prompt record supports at most {_OUTPUT_LIMIT} outputs",
            )
        name = _safe_name(request.name)
        try:
            source = request.output.resolve(strict=True)
            if source.suffix.lower() != ".png":
                raise PortFailure(
                    "invalid_prompt", "Registered prompt outputs must be PNG files"
                )
            _regular_input(source, _PNG_LIMIT)
            validate_format(source)
        except (OSError, ValueError, PortFailure) as exc:
            raise PortFailure(
                "invalid_prompt", f"Invalid prompt output {request.output}: {exc}"
            ) from exc
        output_dir = record.record / "outputs"
        try:
            output_dir.mkdir(exist_ok=True)
            if not output_dir.resolve().is_relative_to(record.record):
                raise ValueError("directory escapes its record")
        except (OSError, ValueError) as exc:
            raise PortFailure(
                "invalid_prompt", f"Prompt output directory is invalid: {exc}"
            ) from exc
        target = output_dir / name
        registration = output_dir / f"{name}.json"
        if (
            target.exists()
            or registration.exists()
            or any(item.name == name for item in record.outputs)
        ):
            raise PortFailure(
                "destination_conflict", f"Prompt output already exists: {name}"
            )
        reserved = False
        try:
            registration.touch(exist_ok=False)
            reserved = True
            copy_with_sha256(source, target, max_bytes=_PNG_LIMIT)
            fact = _png_facts(source, target)
            output = PromptOutput(
                name,
                fact,
                request.submitted_prompt,
                dict(request.caller_declarations),
                request.reported_provider,
                request.reported_model,
                dict(request.reported_options),
            )
            value = _OUTPUT.dump_python(output, mode="json")
            value["file"]["path"] = str(fact.path.relative_to(record.record))
            with registration.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
            updated = PromptRecord(
                **{**record.__dict__, "outputs": (*record.outputs, output)}
            )
            return updated
        except (OSError, PortFailure) as exc:
            if reserved:
                target.unlink(missing_ok=True)
                registration.unlink(missing_ok=True)
            if isinstance(exc, PortFailure):
                raise
            raise PortFailure(
                "prompt_stage_failed", f"Could not register prompt output: {exc}"
            ) from exc
