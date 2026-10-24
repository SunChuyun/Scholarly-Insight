# Scholarly Insight

Scholarly Insight helps users discover scholarly papers through the arXiv API, with a web frontend and a Python backend developed collaboratively.

## Current milestone

The midterm implementation focuses on the backend:

- Search arXiv by keyword.
- Return matching paper metadata as JSON.
- Retrieve results in pages of 20 papers.
- Handle invalid inputs, upstream failures, and arXiv request limits.
- Expose a lightweight backend health endpoint.
- Provide automated tests and a documented frontend integration contract.

The `frontend` directory currently contains only an empty `.gitkeep` placeholder. Databases, accounts, saved papers, reading history, and publication alerts are outside the current backend scope. Later features will be selected after midterm feedback and team planning.

## Repository structure

```text
.
├── README.md
├── .gitignore
├── requirements.txt
├── frontend/
│   └── .gitkeep
└── backend/
    ├── README.md
    ├── __init__.py
    ├── arxiv_client.py
    ├── app.py
    └── tests/
        └── test_backend.py
```

## Running and integrating the backend

The project uses a Conda environment named `scholar` and one root-level `requirements.txt`. Create the environment once, then run all commands from the repository root:

```bash
conda create --name scholar --override-channels --channel conda-forge python=3.12 pip --yes --no-default-packages
conda activate scholar
python -m pip install -r requirements.txt
python -m backend.app
```

Run automated tests from the same directory:

```bash
python -m unittest discover -s backend/tests -v
```

See the [backend README](backend/README.md) for endpoint parameters, JSON responses, frontend integration, and detailed testing instructions.

## Development conventions

All project-authored code, comments, documentation, interface text, and Git commit messages use English. Preserve author names and source metadata accurately.

Agent-assisted changes must not be committed or pushed without an explicit request. Each explicit request for one commit authorizes one commit with an English message.
