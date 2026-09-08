# Preserve prompts before generation

The prompt commands save one attempt in an ordinary directory chosen by the
caller. They require no Godot project, engine, provider credentials, or network
connection. Use separate directories for separate attempts and manage them with
your existing version control.

Prepare a plain prompt before calling an external tool:

```sh
gda asset-pipeline prompt-prepare --record ./art/prompts/attempt-a \
  --text 'A small blue robot with a round head, front and side views.' --json
```

Preparation returns an external generation handoff with the saved prompt and
reference paths. Use these saved inputs when invoking the tool. The command does
not invoke an image generator or claim that an image was generated. An external
failure or unknown completion leaves the prepared inputs available.

## Compose project inputs

A template file uses Python's
[simple template syntax](https://docs.python.org/3.13/library/string.html#template-strings)
with `$name` or `${name}` placeholders. Supply string values
in `--variables`; `$$` writes a literal dollar sign. Missing or unused variables
and invalid placeholder syntax fail preparation. Plain `--text` is literal and
does not substitute variables.

An optional style file precedes the resolved main prompt, separated by a blank
line. The attempt preserves its authored inputs, resolved text, and copies of the
selected PNG reference files. Later source edits do not change those saved inputs.

```sh
gda asset-pipeline prompt-prepare --record ./art/prompts/attempt-b \
  --template ./art/subject.txt --style ./art/style.txt \
  --variables '{"subject":"blue robot"}' \
  --reference ./art/palette.png --json
```

The template can contain `Three views of a $subject.`. Reference files must be
valid PNG images; the initial path does not accept other reference formats.
Preparation refuses an existing record destination.

## Reuse and revise

```sh
gda asset-pipeline prompt-inspect --record ./art/prompts/attempt-a --json

gda asset-pipeline prompt-revise --source-record ./art/prompts/attempt-b \
  --record ./art/prompts/attempt-c \
  --variables '{"subject":"orange robot"}' --json
```

Inspection returns the saved input without calling a producer. Internal file links
resolve from the record directory, so inspection works in a new process or from
another working directory. Command-line input paths resolve from the caller's
working directory; pass an absolute record path when working elsewhere.

Revision starts from the earlier saved inputs, applies explicit replacements, and
writes a new record. Its result identifies the changed fields. It does not update
the prior record or create a global revision history.

## Register a completed output

After an external tool returns a local PNG, associate it with the prepared attempt:

```sh
gda asset-pipeline prompt-register-output --record ./art/prompts/attempt-a \
  --output ./generated/robot.png --name robot.png \
  --caller-declarations '{"tool":"external image tool","generation_completed":true}' \
  --submitted-prompt 'A small blue robot with a round head, front and side views.' --json
```

Registration validates and preserves the local output. It does not call or retry
the producer. Missing or invalid output files fail without removing the prompt or
earlier registered outputs. An existing output name is refused.

Requested settings, caller declarations, and provider-reported details remain
separate. Supply the exact actually submitted prompt when it differs from the
prepared text; omitted dispatch information remains unknown. A registered local
file does not independently prove provider execution, and identical prompts do
not guarantee identical images. Do not place secrets in prompt text or metadata.

`--requested-options` and `--reported-options` accept a JSON object with these
selected keys: `aspect_ratio`, `background`, `model`, `output_format`, `quality`,
`seed`, `size`, and `style`. Values are JSON scalars. These values are recorded;
they do not configure or validate a remote provider. `--reported-provider` and
`--reported-model` retain facts returned by the external tool. Use
`--caller-declarations` for `tool`, `provider`, `model`, `request_id`, and
`generation_completed` supplied by the caller. A completion declaration stays
separate from the record's unknown independently verified generation status.

Read `preparation.record` and `preparation.handoff` after prepare or inspect;
`revision.preparation` and `revision.changed_fields` after revision; and
`prompt_record.outputs` after registration. Output registration preserves a PNG
copy and its own metadata without rewriting the saved preparation inputs.

The initial limits are 16 reference images, 64 output registrations per record,
64 variables, 1 MiB per text input/resolved prompt, and 4 MiB per JSON record or
registration. Each PNG is limited to 256 MiB and 64 megapixels. Variable names
are at most 128 characters and values at most 4,096 characters. Save another
attempt when you need another group of outputs.

Use each command's `--schema` for the supported input and result fields.
The same input is available through `--params-json` and generated MCP. Successful
local preparation, inspection, revision, or registration exits 0; invalid input or
file operations fail with a structured error.

Prompt records are optional for existing-file admission and saved Blender export.
`gda asset-pipeline run` and ordinary resource, scene, and game operations keep
their independent contracts. Concept selection and authoring-reference consumers
are tracked separately by [#913](https://github.com/aigengame/godot-agent/issues/913).
