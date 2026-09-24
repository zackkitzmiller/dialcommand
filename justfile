# DialCommand task runner — prefer `just <recipe>` over raw tools.

fmt:
    black --line-length 80 .

fmt-check:
    black --check --line-length 80 .

test *args:
    pytest {{ args }}

lint: fmt-check
    @echo "format check ok"
