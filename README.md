eza --tree -a \
-I '.git|.venv|__pycache__|node_modules|dist|build|output|logs|.pytest_cache|.mypy_cache|.cache|.idea|.vscode|*.pyc|*.pyo|*.db|*.log|output.txt|tree.txt' \
> tree.txt


eza --tree > tree.txt

source .venv/bin/activate