# Passage citations — what is resolved and what needs a person

**Generated 2026-10-28** by `app/backend/scripts/passage_citations_report.py`
from the frozen evidence sets (`advandeb_methods/data/evidence/evidence_sets_v1.0.json`)
joined against ArangoDB `documents` (read-only), with OpenAlex and Crossref
for the gaps. Full counts: [`citations/summary.txt`](citations/summary.txt).
Machine-readable: `citations/unresolved_citations.csv`, `citations/doi_check.csv`,
`citations/citation_corrections.json`.

## Where things stand

"Full" here means authors, year, a real title and a DOI. The platform shows a
citation as complete without a DOI (books, theses) and marks only passages
with no identified source as *Source not yet identified*.

| | DEB literature (1,116 passages) | Reproduction abstracts (1,116 passages) |
|---|---|---|
| Full from ArangoDB today | 922 (82.6%) — but 201 of them carry a wrong DOI | 122 (10.9%) — 857 of 961 records have no authors |
| Title known, citation incomplete | 52 (4.7%) | 992 (88.9%) |
| Source not identified (file name only) | 142 (12.7%) | 2 (0.2%) |
| **Wrong DOI shown today** | **201 passages, 44 papers** | 0 in a sample of 50 |
| Full after the high-confidence corrections | 865 (77.5%) | 1,032 (92.5%) |
| Complete, but no DOI exists (books, theses) | 72 documents / 140 passages across both | |
| Still needs a person | 36 papers / 170 passages | 21 records / 29 passages |

14 DEB papers are not in ArangoDB at all, among them `Kooy2010.pdf` — the
third edition of the DEB book, cited by 49 passages. A correction cannot fix
those: they need a curated `documents` record (or a re-ingest), after which the
serve-time join picks them up.

## Before experts start: fix the wrong DOIs

44 curated DEB papers carry a DOI that belongs to a different work, or a
malformed one. Most are PhD theses given a similarly titled article's DOI;
others are journal article ids stored as DOIs (`coac039`), an Elsevier PII, a
space inside the DOI, and `10.1016/j.jtbi.2006.09.001/c3`. `Kooy93.pdf`, cited
by 30 passages, carries the DOI of an IEEE Transactions on Magnetics paper.

The fixes are in `citations/citation_corrections.json` (high confidence only).
Apply them with `app/backend/scripts/apply_citation_corrections.py`: dry run by
default, refuses any value that changed since the report, saves every touched
value before `--apply`, and `--revert` undoes it. Dry run, 2026-10-28:

| | Records | Passages whose citation changes |
|---|---|---|
| `--fields doi` | 74 (38 `documents` + 36 `document_meta`) | 155 |
| all fields (doi, title, authors, year, journal) | 1,010 | 1,215 |

**Not applied** — a production write, which needs the project owner's OK.

### Highest-impact DOI problems
| Library # | File | Passages | Status | Stored DOI | Proposed |
|---|---|---|---|---|---|
| 2801 | Kooy93.pdf | 30 | doi_mismatch | `10.1109/20.280868` | `no DOI` (high) |
| 3639 | Davis - 2021 - PHYSIOLOGICAL, MOLECULAR, AND  ECOLOGICAL RES | 24 | doi_mismatch | `10.1016/j.aqrep.2021.100655` | — (none) |
| 2939 | Zonn98b.pdf | 19 | doi_malformed | `0304-3800(98)00134-3` | `10.1016/s0304-3800(98)00134-3` (high) |
| 2902 | Sous2007.pdf | 18 | doi_mismatch | `10.2495/eco-v1-n1-9-27` | `no DOI` (high) |
| 3499 | Lee - 2020 - Towards improved predictions of growth and meta | 14 | doi_mismatch | `10.1016/j.ecolmodel.2020.109055` | — (none) |
| 3124 | Meer2018.pdf | 10 | doi_mismatch | `10.1371/journal.pbio.2005628` | `10.1016/b978-0-12-409548-9.10568-8` (high) |
| 2937 | Zimm2013.pdf | 6 | doi_mismatch | `10.1371/journal.pone.0109796` | `no DOI` (high) |
| 2993 | Kooy88c.pdf | 6 | doi_mismatch | `10.1016/j.ecolmodel.2023.110591` | — (none) |
| 3103 | Glaz2014.pdf | 6 | doi_malformed | `10.3390/systems20 40451` | `10.3390/systems2040451` (high) |
| 2660 | Leeu2003.pdf | 5 | doi_mismatch | `10.1002/cncr.11018` | `no DOI` (high) |
| 2424 | Cabanillas - 2024 - From fronds to forests Applying dynamic  | 4 | doi_mismatch | `10.1016/j.ecolmodel.2024.110869` | — (none) |
| 2909 | Teix2015.pdf | 4 | doi_mismatch | `10.1093/biosci/biv013` | `no DOI` (high) |
| 3589 | Kooijman - 1986 - Population dynamics on the basis of budget | 4 | doi_mismatch | `10.2166/wst.1987.0109` | `10.1007/978-94-011-2446-1_4` (medium) |
| 2534 | Arnould-Petre - 2019 - MODEL OF A SEA URCHIN ENDEMIC TO THE  | 3 | doi_mismatch | `10.1002/ece3.4091` | `10.1016/j.ecolmodel.2020.109352` (medium) |
| 2650 | Main2015.pdf | 3 | doi_mismatch | `10.1146/annurev-ento-010814-020841` | `no DOI` (high) |

## DEB papers that need manual completion

Sorted by how many passages cite them. "Best candidate" is a lookup by file
key and title — **often wrong** at low or medium confidence: check it against
the PDF in `/home/adeb/DEB_library/<#>/`. Kooijman-group keys follow the DEB
bibliography convention (`Kooy93` = Kooijman 1993, `Kooy2010_c` = a companion
document of the 2010 book). The OpenAlex search budget ran out during the run;
re-running the report after 00:00 UTC may add candidates for about eight
theses (cached answers are reused).

| Library # | File | Passages | Best candidate (confidence) |
|---|---|---|---|
| 2367 | Kooy2010_c.pdf | 26 | Sebastiaan A. L. M. Kooijman (2010). Dynamic Energy Budget Theory for Metabolic Organisation. Cambridge Univer (medium) |
| 3639 | Davis - 2021 - PHYSIOLOGICAL, MOLECULAR, AND  ECOLOGICAL RES | 24 | — (none) |
| 3525 | Kooy2010_i.pdf | 18 | Sebastiaan A. L. M. Kooijman (2010). Dynamic Energy Budget Theory for Metabolic Organisation. Cambridge Univer (medium) |
| 3315 | Lew2015.pdf | 17 | — (none) |
| 3499 | Lee - 2020 - Towards improved predictions of growth and meta | 14 | — (none) |
| 2986 | Kooy2012.pdf | 10 | S. A. L. M. Kooijman (2019). Energy Budgets. Encyclopedia of Theoretical Ecology: 249-258. https://doi.org/10. (medium) |
| 2993 | Kooy88c.pdf | 6 | — (none) |
| 3532 | Mauritsson - 2020 - EFFECTS OF PCB ON THE POPULATION GROWTH  | 5 | — (none) |
| 2424 | Cabanillas - 2024 - From fronds to forests Applying dynamic  | 4 | — (none) |
| 3589 | Kooijman - 1986 - Population dynamics on the basis of budget | 4 | S. A. L. M. Kooijman, E. B. Muller, A. H. Stouthamer (1992). Microbial growth dynamics on the basis of individ (medium) |
| 2534 | Arnould-Petre - 2019 - MODEL OF A SEA URCHIN ENDEMIC TO THE  | 3 | Margot Arnould-Pétré, Charlène Guillaumot, Bruno Danis et al. (2020). Individual-based model of population dyn (medium) |
| 2804 | Kooy97.pdf | 3 | — (none) |
| 2974 | KooyBeda2006.pdf | 3 | — (none) |
| 3412 | Klein - 2018 - analysis and optimization of ecotoxicological | 3 | — (none) |
| 2839 | Kooy2015_en.pdf | 2 | — (none) |
| 2863 | Camp2009.pdf | 2 | J Campos, A Bio, JFMF Cardoso et al. (2010). Fluctuations of brown shrimp Crangon crangon abundance in the wes (medium) |
| 3303 | Wier2005.pdf | 2 | — (none) |
| 3320 | Jaco2011.pdf | 2 | — (none) |
| 3328 | McFa2015.pdf | 2 | — (none) |
| 3358 | Candela - 2018 - Linking individual behaviour and life histo | 2 | — (none) |
| 3584 | Trestrial - 2022 - Microplastics-induced energy flux in the  | 2 | — (none) |
| 3674 | FroePaul2023_comment.pdf | 2 | Rainer Froese, Daniel Pauly (2023). Comment on “Metabolic scaling is the product of life-history optimization” (medium) |
| 2449 | Oliveira - 2024 - Demography of the Mussel, An Engineering S | 1 | — (none) |
| 2452 | Kear2024.pdf | 1 | — (none) |
| 2788 | KonaKooy98.pdf | 1 | Marek Konarzewski, Sebaastian A L M Kooijman, Robert E. Ricklefs (1998). Models for Avian Growth and Developme (medium) |
| 3163 | JageRava2015.pdf | 1 | T Jager, E Ravagnan (2015). Parameterising a generic model for the dynamic energy budget of Antarctic krill Eu (medium) |
| 3202 | Frei2011.pdf | 1 | — (none) |
| 3306 | WijsDede2012.pdf | 1 | — (none) |
| 3307 | Zhan2011.pdf | 1 | — (none) |
| 3345 | Beaudouin - 2019 - Modélisation du lien organisme – populati | 1 | — (none) |
| 3433 | Martin - 2013 - .pdf | 1 | — (none) |
| 3510 | Menu - 2020 - Modélisation bioénergétique de la variabilité  | 1 | — (none) |
| 3629 | Roberts - 2014 - Energy and mass budgets of kangaroos  and t | 1 | — (none) |
| 3747 | JusuKear2024.pdf | 1 | — (none) |
| 3755 | JusuLava2024.pdf | 1 | Samuel C. Ginther, Hayley Cameron, Craig R. White et al. (2024). Metabolic loads and the costs of metazoan rep (medium) |
| 3831 | Harwood et al. - 2022 - Final Report Further Development Of  | 1 | — (none) |

## Reproduction abstracts

| OpenAlex id | Title as recorded | Passages | Best candidate (confidence) |
|---|---|---|---|
| W3086759072 | Decision letter: Nutrient levels and trade-offs control dive | 5 | — (none) |
| W2363891221 | The Effects of Nitrogen Limitation on Terrestrial Ecosystem  | 3 | — (none) |
| W3084989369 | Author response: Nutrient levels and trade-offs control dive | 2 | Amir Erez, Jaime G Lopez, Benjamin Weiner et al. (2020). Author response: Nutrient levels and trade-offs contr (high) |
| W4249971058 | Peer Review #2 of "On the exponent in the Von Bertalanffy gr | 2 | — (none) |
| W143266977 | Energy metabolism in animals and man | 1 | — (none) |
| W1542859152 | Possible parthenogenesis in Allopauropus (Myriapoda: Pauropo | 1 | Ulf Scheller (1999). New Species in Allopauropus (Myriapoda: Pauropoda) from East Africa. International Journa (medium) |
| W1567791168 | Technical and economic aspects of potential U. S. district h | 1 | J. Karkheck, E. Beardsworth, J. Powell (1976). Technical and Economic Feasibility of U. S. District Heating Sy (medium) |
| W2062924031 | Proportionality between in situ carbon assimilation and bio‐ | 1 | — (none) |
| W2078621949 | Correction: Metabolic Rate Regulates L1 Longevity in C. eleg | 1 | Inhwan Lee, Amber Hendrix, Jeongho Kim et al. (2013). Correction: Metabolic Rate Regulates L1 Longevity in C.  (high) |
| W2138845720 | Ageing and typical survivorship curves result from optimal r | 1 | M. Cichoń (2001). Diversity of age-specific reproductive rates may result from ageing and optimal resource all (medium) |
| W2315945317 | Erratum: Constraints on the Offspring Production Efficiency  | 1 | Douglas Stewart Glazier (1990). Erratum: Constraints on the Offspring Production Efficiency of Peromyscus and  (high) |
| W2361342252 | ECOLOGICAL STOICHIOMETRY: A SCIENCE TO EXPLORE THE COMPLEXIT | 1 | ZENG De-Hui, Daqinggou Ecological Station, Institute of Applied Ecology, Chinese Academy of Sciences, Shenyang (high) |
| W2391514266 | STUDIES on the STRATEGIES of MATEEERNAL PRODUCTION in MAMMAL | 1 | — (none) |
| W3033329383 | Growth hormone (GH) and reproduction : a short review | 1 | Florence Le Gac, Odile Blaise, Alex Fostier et al. (1993). Growth hormone (GH) and reproduction: a review. Fis (medium) |
| W4239249889 | Thwack of Worldwide Weather Transformation on Vector and Vec | 1 | — (none) |
| W4244764665 | (untitled) | 1 | — (none) |
| W4249779047 | Decision letter: The Human Cell Atlas | 1 | — (none) |
| W4250859894 | This Week in The Journal | 1 | — (none) |
| W4293167250 | (untitled) | 1 | — (none) |
| W4387667109 | Proceedings of the V International Scientific and Practical  | 1 | — (none) |
| W92114755 | Basal reproductive hormonal profiles are altered in enduranc | 1 | A C HACKNEY, W E SINNING, B C BRUOT (1988). Reproductive hormonal profiles of endurance-trained and untrained  (medium) |

Five reproduction `document_id`s point at unrelated OpenAlex works (one is a
1965 reactor-physics report); the platform keeps the passage's own title and
DOI for those rather than joining the wrong record. Nine records are referee
reports or decision letters, and 37 are preprints OpenAlex has merged into the
published version.
