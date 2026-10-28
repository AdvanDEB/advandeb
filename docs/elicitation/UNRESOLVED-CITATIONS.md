# Passage citations — what is resolved and what needs a person

**Generated 2026-10-28** by `app/backend/scripts/passage_citations_report.py`
from the frozen evidence sets (`advandeb_methods/data/evidence/evidence_sets_v1.0.json`)
joined against ArangoDB `documents` (read-only), with OpenAlex and Crossref
for the gaps. Full counts: [`citations/summary.txt`](citations/summary.txt).
Machine-readable: `citations/unresolved_citations.csv`, `citations/doi_check.csv`,
`citations/citation_corrections.json`.

## Where things stand

| | DEB literature (1,116 passages) | Reproduction abstracts (1,116 passages) |
|---|---|---|
| Full citation from ArangoDB today | 922 passages (82.6%) | 122 (10.9%) — most records lack authors/journal |
| Title shown but citation incomplete | 52 (4.7%) | 992 (88.9%) |
| Source not identified (file name only) | 142 (12.7%) | 2 (0.2%) |
| **Wrong DOI shown today** | **201 passages, 44 papers** | 1 passage |
| Full after applying the high-confidence corrections | 861 (77.2%) + books confirmed without DOI | 1,031 (92.4%) |
| Still needs a person | 36 papers / 174 passages | 119 records / 131 passages (of which 75 / 84 flagged for manual work) |

(The DEB "full" share falls after correction because wrong DOIs are removed,
not replaced, where no right one could be confirmed.)

## Before experts start: fix the wrong DOIs

44 curated DEB papers carry a DOI that resolves to a different work, or a
malformed one (e.g. `Kooy93.pdf` → an IEEE Transactions on Magnetics paper;
`10.1016/j.jtbi.2006.09.001/c3`). The fixes are in
`citations/citation_corrections.json`; apply them to ArangoDB with
`app/backend/scripts/apply_citation_corrections.py` — dry run by default, a
backup of every touched value before `--apply`, `--revert` to undo. Dry run on
2026-10-28: `--fields doi` changes 74 records (38 `documents` + 36
`document_meta`), 155 passages; all fields: 1,011 records, 1,217 passages,
nothing skipped. **Not applied** — that is a production write and needs the
project owner's OK.

### Highest-impact DOI problems
| Library # | File | Passages | Status | Stored DOI | Proposed |
|---|---|---|---|---|---|
| 2801 | Kooy93.pdf | 30 | doi_mismatch | `10.1109/20.280868` | `no DOI` (high) |
| 3639 | Davis - 2021 - PHYSIOLOGICAL, MOLECULAR, AND  ECOLOGICAL RES | 24 | doi_mismatch | `10.1016/j.aqrep.2021.100655` | `10.1002/ieam.4437` (medium) |
| 2939 | Zonn98b.pdf | 19 | doi_malformed | `0304-3800(98)00134-3` | `10.1016/s0304-3800(98)00134-3` (high) |
| 2902 | Sous2007.pdf | 18 | doi_mismatch | `10.2495/eco-v1-n1-9-27` | `no DOI` (high) |
| 3499 | Lee - 2020 - Towards improved predictions of growth and meta | 14 | doi_mismatch | `10.1016/j.ecolmodel.2020.109055` | `10.3390/su13010017` (medium) |
| 3124 | Meer2018.pdf | 10 | doi_mismatch | `10.1371/journal.pbio.2005628` | `10.1016/b978-0-12-409548-9.10568-8` (high) |
| 2937 | Zimm2013.pdf | 6 | doi_mismatch | `10.1371/journal.pone.0109796` | `no DOI` (high) |
| 2993 | Kooy88c.pdf | 6 | doi_mismatch | `10.1016/j.ecolmodel.2023.110591` | `10.14288/1.0074762` (low) |
| 3103 | Glaz2014.pdf | 6 | doi_malformed | `10.3390/systems20 40451` | `10.3390/systems2040451` (high) |
| 2660 | Leeu2003.pdf | 5 | doi_mismatch | `10.1002/cncr.11018` | `no DOI` (high) |
| 2424 | Cabanillas - 2024 - From fronds to forests Applying dynamic  | 4 | doi_mismatch | `10.1016/j.ecolmodel.2024.110869` | `10.48550/arxiv.2408.08240` (medium) |
| 2909 | Teix2015.pdf | 4 | doi_mismatch | `10.1093/biosci/biv013` | `no DOI` (high) |
| 3589 | Kooijman - 1986 - Population dynamics on the basis of budget | 4 | doi_mismatch | `10.2166/wst.1987.0109` | `10.1007/bf00276955` (medium) |
| 2534 | Arnould-Petre - 2019 - MODEL OF A SEA URCHIN ENDEMIC TO THE  | 3 | doi_mismatch | `10.1002/ece3.4091` | `10.1016/j.ecolmodel.2020.109352` (medium) |
| 2650 | Main2015.pdf | 3 | doi_mismatch | `10.1146/annurev-ento-010814-020841` | `no DOI` (high) |

## DEB papers that need manual completion

Sorted by how many passages cite them. "Best candidate" is a lookup by file
key and title — **often wrong** (low/medium confidence): check it against the
PDF in `/home/adeb/DEB_library/<#>/`. Kooijman-group keys follow the DEB
bibliography convention (`Kooy93` = Kooijman 1993, `Kooy2010_c` = a chapter
of the 2010 book).

| Library # | File | Passages | Best candidate (confidence) |
|---|---|---|---|
| 2367 | Kooy2010_c.pdf | 26 | Sebastiaan A. L. M. Kooijman (2010). Dynamic Energy Budget Theory for Metabolic Organisation. Cambridge Univer (medium) |
| 3639 | Davis - 2021 - PHYSIOLOGICAL, MOLECULAR, AND  ECOLOGICAL RES | 24 | Jenny Davis, Paula Whitfield, Danielle Szimanski et al. (2021). A framework for evaluating island restoration  (medium) |
| 3525 | Kooy2010_i.pdf | 18 | Sebastiaan A. L. M. Kooijman (2010). Dynamic Energy Budget Theory for Metabolic Organisation. Cambridge Univer (medium) |
| 3315 | Lew2015.pdf | 17 | R. Lew (2015). Research into the use of online dictionaries. International Journal of Lexicography 28(2): 232- (medium) |
| 3499 | Lee - 2020 - Towards improved predictions of growth and meta | 14 | Kyounga Lee, Jongmun Cha (2020). Towards Improved Circular Economy and Resource Security in South Korea. Susta (medium) |
| 2986 | Kooy2012.pdf | 10 | S. A. L. M. Kooijman (2019). Energy Budgets. Encyclopedia of Theoretical Ecology: 249-258. https://doi.org/10. (medium) |
| 2993 | Kooy88c.pdf | 6 | Maria Lourdes D. Palomares, Daniel F Pauly (2012). Von Bertalanffy growth parameters of non-fish marine organi (low) |
| 3532 | Mauritsson - 2020 - EFFECTS OF PCB ON THE POPULATION GROWTH  | 5 | Karl Mauritsson, Jean-Pierre Desforges, Karin Harding (2022). Maternal Transfer and Long-Term Population Effec (low) |
| 2424 | Cabanillas - 2024 - From fronds to forests Applying dynamic  | 4 | Wilson Cabanillas B (2024). A note about an upper bound for a hitting time of the fractional Ornstein-Uhlenbec (medium) |
| 3589 | Kooijman - 1986 - Population dynamics on the basis of budget | 4 | S. A. L. M. Kooijman (1986). What the hen can tell about her eggs: egg development on the basis of energy budg (medium) |
| 2534 | Arnould-Petre - 2019 - MODEL OF A SEA URCHIN ENDEMIC TO THE  | 3 | Margot Arnould-Pétré, Charlène Guillaumot, Bruno Danis et al. (2020). Individual-based model of population dyn (medium) |
| 2804 | Kooy97.pdf | 3 | Martin Kooijman, R. Orsel, Martin Hessing et al. (1997). Spectroscopic Characterisation of the Lipid-binding P (medium) |
| 2974 | KooyBeda2006.pdf | 3 | Piet G. C. Kooijman (2006). The voice of the teacher. A multidimensional and dynamic process.. Radboud Reposit (medium) |
| 3412 | Klein - 2018 - analysis and optimization of ecotoxicological | 3 | Olaf Klein (2019). On Uncertainty Quantification for Models Involving Hysteresis Operators. Trends in Mathemat (low) |
| 2839 | Kooy2015_en.pdf | 2 | Matthijs Kooijman (2015). Building Wireless Sensor Networks Using Arduino. Packt Publishing eBooks. (low) |
| 2863 | Camp2009.pdf | 2 | Joana Campos, Henk W. Van der Veer, Vânia Freitas et al. (2009). Contribution of different generations of the  (medium) |
| 3303 | Wier2005.pdf | 2 | Christian Maes, Maarten H van Wieren (2005). Thermoelectric phenomena via an interacting particle system. Jour (low) |
| 3320 | Jaco2011.pdf | 2 | Anne McCarthy Jacobson (2011). Stroke Recovery and Rehabilitation. Journal of Neurologic Physical Therapy 35(1 (medium) |
| 3328 | McFa2015.pdf | 2 | Katherine McFarland, Fred Jean, Philippe Soudant et al. (2015). Uptake and elimination of brevetoxin in the in (medium) |
| 3358 | Candela - 2018 - Linking individual behaviour and life histo | 2 | Chiara Candela, Annalaura Di Pumpo, Alessandro Centonze et al. (2018). Transcatheter aortic valve replacement: (medium) |
| 3584 | Trestrial - 2022 - Microplastics-induced energy flux in the  | 2 | Paula Masiá, Alba Ardura, Eva Garcia-Vazquez (2022). Microplastics in seafood: Relative input of Mytilus gallo (low) |
| 3674 | FroePaul2023_comment.pdf | 2 | Rainer Froese, Daniel Pauly (2023). Comment on “Metabolic scaling is the product of life-history optimization” (medium) |
| 2449 | Oliveira - 2024 - Demography of the Mussel, An Engineering S | 1 | Jocelito Oliveira de Oliveira (2024). The valuation of the cultural heritage of val verones from the tourism d (medium) |
| 2452 | Kear2024.pdf | 1 | Daithí Kearney (2024). A NEED FOR PIED PIPERS? MAKING CONNECTIONS IN A COMMUNITY ARTS SONG-MAKING PROJECT. Cul (medium) |
| 2788 | KonaKooy98.pdf | 1 | Marek Konarzewski, Sebaastian A L M Kooijman, Robert E. Ricklefs (1998). Models for Avian Growth and Developme (medium) |
| 3163 | JageRava2015.pdf | 1 | T Jager, E Ravagnan (2015). Parameterising a generic model for the dynamic energy budget of Antarctic krill Eu (medium) |
| 3202 | Frei2011.pdf | 1 | Nando de Freitas (2011). Toward the Implementation of a Quantum RBM. (medium) |
| 3306 | WijsDede2012.pdf | 1 | Ellen M. Wijsman, Nathan D. Pankratz, Yoonha Choi et al. (2011). Genome-Wide Association of Familial Late-Onse (low) |
| 3307 | Zhan2011.pdf | 1 | Lai Zhang, Zhigui Lin, Michael Pedersen (2011). Effects of Growth Curve Plasticity on Size-Structured Populati (medium) |
| 3345 | Beaudouin - 2019 - Modélisation du lien organisme – populati | 1 | Vanessa Beaudouin, Laure Sugier, Philippe Robert-Demontrond (2019). Une lecture expérientielle du phénomène de (medium) |
| 3433 | Martin - 2013 - .pdf | 1 | Benjamin T. Martin, Tjalling Jager, Roger M. Nisbet et al. (2013). Predicting Population Dynamics from the Pro (medium) |
| 3510 | Menu - 2020 - Modélisation bioénergétique de la variabilité  | 1 | Flavien Menu (2020). Transformer la culture de l’habiter. Tous urbains N° 30-31(2): 22-29. https://doi.org/10. (medium) |
| 3629 | Roberts - 2014 - Energy and mass budgets of kangaroos  and t | 1 | B. R. Roberts (2014). Archipelagic American Literary History and the Philippines. American Literary History 27 (medium) |
| 3747 | JusuKear2024.pdf | 1 | [authors missing] (2003). Proceedings of the Third World Fisheries Congress: Feeding the World with Fish in th (low) |
| 3755 | JusuLava2024.pdf | 1 | Samuel C. Ginther, Hayley Cameron, Craig R. White et al. (2024). Metabolic loads and the costs of metazoan rep (medium) |
| 3831 | Harwood et al. - 2022 - Final Report Further Development Of  | 1 | Andrew J.P. Harwood, Sue King (2022). Seabirds and Marine Renewable Energy Sources. Seabird Biodiversity and H (medium) |

## Reproduction abstracts

75 records (84 passages) are flagged for manual completion after
OpenAlex enrichment; they already show their title and year.
Listed in `citations/unresolved_citations.csv` (`corpus = reproduction`,
`needs_manual = yes`). 15 passages carry an OpenAlex id that points at an
unrelated work; the platform now keeps the passage's own title and DOI for
those instead of joining the wrong record.
