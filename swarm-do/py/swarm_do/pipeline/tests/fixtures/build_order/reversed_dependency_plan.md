### Phase 1: Wire CLI

Call the application helper from the CLI before the helper exists.

### File Targets

- `bin/swarm`

### Acceptance Criteria

- CLI calls the helper.

### Validation Commands

```bash
python3 py/app.py
```

### Phase 2: Add helper

Create the helper consumed by phase 1.

### File Targets

- `py/app.py`

### Acceptance Criteria

- Helper exists.

### Validation Commands

```bash
python3 py/app.py
```
