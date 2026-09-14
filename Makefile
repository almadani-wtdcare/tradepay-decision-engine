.PHONY: run test docker-up docker-test demo data standalone
run:        ; uvicorn app.main:app --reload --port 8080
test:       ; python -m pytest -v
docker-up:  ; docker compose up --build
docker-test:; docker compose --profile test run --rm tests
demo:       ; ./scripts/demo.sh
data:       ; python -m data.generate_history
standalone: ; python scripts/build_standalone_demo.py
