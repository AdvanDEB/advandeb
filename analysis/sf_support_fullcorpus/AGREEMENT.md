# Validation — cross-judge agreement & corpus-fix impact

## gpt-oss:120b vs Claude Opus 4.8 (evidence strength)

| Scope | Exact match | Within ±1 | Mean (gpt-oss − Claude) |
|-------|:-----------:|:---------:|:-----------------------:|
| deb | 79% | 100% | +0.08 |
| reproduction | 60% | 98% | +0.32 |
| combined | 79% | 100% | +0.02 |

## gpt-oss:120b vs Claude Opus 4.8 (consensus direction)

| Scope | Exact match | Within ±1 |
|-------|:-----------:|:---------:|
| deb | 84% | 100% |
| reproduction | 69% | 98% |
| combined | 85% | 98% |

## Impact of fixing the corpus (reproduction side, Claude judge)

Old = 0.6 M ChromaDB subset (MiniLM). New = full ~3.9 M unique abstracts (nomic).

| SF | old Ev | new Ev | Δ | old refs | new refs |
|----|:------:|:------:|:-:|:--------:|:--------:|
| `feeding_01` | 2 | 1 | -1 | 7 | 6 |
| `feeding_02` | 2 | 3 | +1 | 9 | 17 |
| `feeding_03` | 1 | 2 | +1 | 0 | 4 |
| `feeding_04` | 2 | 3 | +1 | 3 | 9 |
| `feeding_05` | 1 | 1 | +0 | 2 | 5 |
| `growth_01` | 3 | 2 | -1 | 15 | 6 |
| `growth_02` | 3 | 3 | +0 | 15 | 13 |
| `growth_03` | 3 | 2 | -1 | 9 | 8 |
| `growth_04` | 1 | 1 | +0 | 0 | 1 |
| `growth_06` | 1 | 1 | +0 | 2 | 4 |
| `growth_07` | 2 | 1 | -1 | 4 | 1 |
| `growth_09` | 2 | 3 | +1 | 3 | 9 |
| `growth_10` | 1 | 1 | +0 | 6 | 8 |
| `growth_11` | 2 | 2 | +0 | 7 | 8 |
| `reproduction_01` | 2 | 2 | +0 | 11 | 8 |
| `reproduction_02` | 1 | 2 | +1 | 6 | 6 |
| `reproduction_03` | 2 | 1 | -1 | 8 | 3 |
| `reproduction_04` | 2 | 3 | +1 | 8 | 13 |
| `respiration_02` | 1 | 1 | +0 | 0 | 1 |
| `respiration_03` | 1 | 1 | +0 | 1 | 2 |
| `respiration_04` | 1 | 1 | +0 | 0 | 5 |
| `respiration_05` | 2 | 1 | -1 | 2 | 1 |
| `stoichiometry_01` | 1 | 2 | +1 | 2 | 11 |
| `stoichiometry_02` | 2 | 2 | +0 | 4 | 6 |
| `genphys_02` | 1 | 1 | +0 | 1 | 6 |
| `genphys_03` | 1 | 1 | +0 | 10 | 5 |
| `genphys_04` | 2 | 1 | -1 | 8 | 3 |
| `genphys_05` | 2 | 2 | +0 | 4 | 6 |
| `genphys_07` | 3 | 2 | -1 | 14 | 18 |
| `genphys_08` | 1 | 2 | +1 | 2 | 6 |
| `hypoxia_01` | 2 | 2 | +0 | 4 | 5 |
| `hypoxia_03` | 1 | 1 | +0 | 0 | 2 |
| `hypoxia_04` | 2 | 1 | -1 | 4 | 4 |
| `hypoxia_05` | 1 | 1 | +0 | 1 | 3 |
| `hypoxia_07` | 3 | 3 | +0 | 9 | 18 |
| `hypoxia_08` | 2 | 2 | +0 | 4 | 6 |
| `hypoxia_09` | 2 | 2 | +0 | 8 | 7 |
| `hypoxia_10` | 3 | 3 | +0 | 8 | 15 |
| `hypoxia_11` | 1 | 2 | +1 | 2 | 10 |
| `hypoxia_12` | 1 | 1 | +0 | 0 | 1 |
| `nc_01` | 1 | 1 | +0 | 0 | 1 |
| `nc_03` | 1 | 1 | +0 | 2 | 1 |
| `chl_01` | 1 | 1 | +0 | 1 | 0 |
| `chl_03` | 1 | 1 | +0 | 0 | 1 |
| `chl_04` | 1 | 2 | +1 | 2 | 4 |
| `eps_01` | 1 | 1 | +0 | 0 | 1 |

**Mean Ev change:** +0.02  ·  **Mean ref change:** +1.1  (raised 10, unchanged 43, lowered 9)
