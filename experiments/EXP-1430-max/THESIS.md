# EXP-1430-max: Genetic Algorithm Strategy Evolver

## Hypothesis

Evolving trading rule combinations (entry conditions, exit conditions,
sizing rules, regime filters) via genetic algorithm discovers non-obvious
strategy configurations that outperform hand-designed ones.

## Method

- Genome: vector of continuous + discrete parameters
- Fitness: Sharpe × √CAGR / max(DD, 0.05), evaluated OOS only
- Population 100, 50 generations, tournament selection
- Crossover: uniform + arithmetic blend
- Mutation: Gaussian perturbation + boundary reflection
- Anti-overfitting: IS/OOS split, fitness = OOS only, parsimony pressure

## Success Criteria

- Evolved strategy Sharpe > 1.5× best hand-designed
- OOS/IS fitness ratio > 0.6 (not overfit)
- ≤20 active genes (parsimony)
- Converges within 50 generations
