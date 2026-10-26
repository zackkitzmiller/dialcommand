# DialCommand task runner — prefer `just <recipe>` over raw tools.

sc_default := home_directory() / "code/StreamController"
sc_dir := env("STREAMCONTROLLER_DIR", sc_default)
venv := justfile_directory() / ".venv"
bin := venv / "bin"

# Build .venv on StreamController's Python, with its source and packages
# importable through a .pth file so editors and tests resolve them.
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    sc_py="{{ sc_dir }}/.venv/bin/python"
    uv venv --allow-existing --python "$sc_py" "{{ venv }}"
    uv pip install --python "{{ bin }}/python" pytest black ruff
    purelib='import sysconfig; print(sysconfig.get_path("purelib"))'
    site="$("{{ bin }}/python" -c "$purelib")"
    printf '%s\n' "{{ sc_dir }}" "$("$sc_py" -c "$purelib")" \
        > "$site/streamcontroller.pth"

fmt:
    {{ bin }}/ruff check --select I --fix .
    {{ bin }}/black --line-length 80 .

fmt-check:
    {{ bin }}/black --check --line-length 80 .

imports-check:
    {{ bin }}/ruff check --select I --diff .

test *args:
    {{ bin }}/pytest {{ args }}

lint: fmt-check
    @echo "format check ok"
