# Convenience targets. Everything here is also reachable as `python3 -m chia_loop`.
PY      ?= python3
CYCLES  ?= 3000
SEEDS   ?= 1,7,42,99,1234
OPS     ?=

.PHONY: help status sim mutate triage formal bmc cover verify check clean

help:
	@echo "status  - show which tools and agent backends are available"
	@echo "sim     - run the property set against the golden RTL"
	@echo "mutate  - score the property set by mutation testing"
	@echo "triage  - mutation campaign plus agent triage of survivors"
	@echo "formal  - unbounded proof via SymbiYosys (needs yosys + sby)"
	@echo "bmc     - bounded model check"
	@echo "cover   - cover reachability (detects over-constraint)"
	@echo "verify  - everything: sim + mutation + bmc + prove + cover"
	@echo "check   - sim + mutate, the gate used before committing"

status:
	@$(PY) -m chia_loop status

sim:
	@$(PY) -m chia_loop sim --cycles $(CYCLES) --seeds $(SEEDS)

mutate:
	@$(PY) -m chia_loop mutate --cycles 2000 --seeds $(SEEDS) --ops "$(OPS)"

triage:
	@$(PY) -m chia_loop mutate --cycles 2000 --seeds $(SEEDS) --triage --ops "$(OPS)"

formal:
	@$(PY) -m chia_loop formal --task prove

bmc:
	@$(PY) -m chia_loop formal --task bmc

cover:
	@$(PY) -m chia_loop formal --task cover

verify:
	@$(PY) -m chia_loop verify --seeds $(SEEDS) --cycles $(CYCLES)

check: sim mutate

clean:
	@rm -rf build reports/*.json reports/*.md formal/freelist_*/ 
	@echo "cleaned"
