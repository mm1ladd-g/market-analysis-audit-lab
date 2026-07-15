.PHONY: setup build doctor smoke demo dashboard down shell collect transcribe manifest extract-claims fetch-outcomes score report pdf finalize verify verify-final run status test lint security-check clean

setup:
	@test -f .env || (umask 077 && cp .env.example .env)
	@mkdir -p workspace/market-data configs/local
	@echo "Created local files. Configure .env before a real collection; use 'make demo' first."

build:
	docker compose build

doctor:
	docker compose run --rm audit-lab python -m audit_lab.cli doctor

smoke:
	docker compose run --rm audit-lab python -m audit_lab.cli smoke

demo:
	docker compose run --rm audit-lab python -m audit_lab.cli demo --workspace /workspace
	docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
	docker compose run --rm audit-lab python -m audit_lab.cli finalize --synthetic-demo --workspace /workspace
	docker compose run --rm audit-lab python -m audit_lab.cli verify-final --synthetic-demo --workspace /workspace

dashboard:
	docker compose up --build audit-web

down:
	docker compose down --remove-orphans

shell:
	docker compose run --rm audit-lab sh

collect:
	docker compose run --rm audit-lab python -m audit_lab.cli collect

transcribe:
	docker compose run --rm audit-lab python -m audit_lab.cli transcribe

manifest:
	docker compose run --rm audit-lab python -m audit_lab.cli manifest

extract-claims:
	docker compose run --rm audit-lab python -m audit_lab.cli extract-claims $(ARGS)

fetch-outcomes:
	docker compose run --rm audit-lab python -m audit_lab.cli fetch-outcomes

score:
	docker compose run --rm audit-lab python -m audit_lab.cli score $(ARGS)

report:
	docker compose run --rm audit-lab python -m audit_lab.cli report

pdf:
	docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace

finalize:
	docker compose run --rm audit-lab python -m audit_lab.cli finalize

verify:
	docker compose run --rm audit-lab python -m audit_lab.cli verify

verify-final:
	docker compose run --rm audit-lab python -m audit_lab.cli verify-final

run:
	docker compose run --rm audit-lab python -m audit_lab.cli run

status:
	docker compose run --rm audit-lab python -m audit_lab.cli status

test:
	docker compose run --rm audit-lab python -m unittest discover -s tests -v

lint:
	docker build --target development -t market-analysis-audit-lab:development .
	docker run --rm --read-only --tmpfs /tmp:size=64m,mode=1777 -e HOME=/tmp -e RUFF_CACHE_DIR=/tmp/ruff-cache \
		market-analysis-audit-lab:development ruff check audit_lab scripts tests

security-check:
	python3 scripts/check_public_release.py

clean:
	@test "$(CONFIRM)" = "YES" || { echo "Refusing to delete workspace. Re-run as: make clean CONFIRM=YES"; exit 1; }
	@echo "Removing every generated or imported artifact under workspace/."
	@find workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
