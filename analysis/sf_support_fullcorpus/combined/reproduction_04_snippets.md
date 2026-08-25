# Evidence snippets — reproduction_04 — Combined (both full corpora)

**Stylized fact:** Egg size (or initial reserve) covaries with the nutritional status of the mother.

Each passage shows both judges' verdicts (G = gpt-oss:120b, C = Claude).

### 1. G:❌contradicts (r0.9) · C:❌contradicts (r0.8) · sim~0.84
*Source:* SchlElln2001.pdf

> hat egg mass is negatively correlated with the food concentration available to the mother (e.g., 88 Schliekelman and Ellner [Page 17] Trubetskova and Lampert, 1995; Gliwicz and Guisande, 1992; Tessier et al., 1983). This variation has been found to range from 10 to 700. It has also been shown (e.g., Gliwicz and Guisande, 1992; Tessier et al., 1983) that juvenile survival times under starvation conditions are positively correlated with egg mass. Glazier (1992) proposed that there should be a convex relationship between offspring investment and maternal food availa- bility: at intermediate food levels, there should be flexibility in egg investment and a parent maximizes fit- ness by increasing

### 2. G:✅supports (r0.8) · C:❌contradicts (r0.8) · sim~0.83
*Source:* Lampert - 2025 - Daphnia magna.pdf

> s of eggs. Sev- eral of them dealing with the connection between egg size and neonate size will be discussed later. Egg sizes were often measured in studies related to the energy budget of D. magna. In a study on energy investment into reproduc- tion, Glazier (1991) developed a qualitative model of egg size in response to food availability. The model pre- dicts that at very low levels of food (near the threshold for growth, cf. 10.8), egg size should increase with food availability as impoverished females are constrained to produce smaller eggs (if any at all). At slightly higher food concentrations, egg size should reach a maximum according to the adaptive response of producing larger (star

### 3. G:❌contradicts (r0.9) · C:❌contradicts (r0.8) · sim~0.81
*Source:* Lampert - 2025 - Daphnia magna.pdf

> ncentrations of food, eggs can get smaller, but more numerous, until a limit of minimum viable offspring size is reached. The effect of the mother’s food level on mass and quality of ﬁrst-brood eggs was investigated by Boersma (1997a). He raised D. magna at four concen- trations of S. acutus (obliquus), 0.1, 0.2, 0.4, and 1.0 mg C L-1 as the ILC is about 0.4 mg C L-1. Eggs were analyzed for their volume, ash-free dry mass (ADM), carbon content, and lipid (triglyceride) content. With increasing food concentration, the egg volume de- creased from 0.037 mm3 egg-1 to 0.025 mm3 egg-1. The ADM per egg decreased as well as the amount of car- bon and lipids (Fig. 12.2). The relative chemical com- po

### 4. G:✅supports (r0.8) · C:✅supports (r0.9) · sim~0.81
*Source:* JageGous2023_suppinfo.pdf

> an egg with such a level of reserve that the embryo hits the maturity level at birth (Eb H) with a scaled reserve density (e) that equals the scaled reserve density of the mother at egg formation. This implies that well-fed mothers produce well-fed offspring, and that egg size will decrease with food limitation (or assimilation stress) of the mother. This is a rather awkward rule, which requires awkward code to implement (see next section). For each value of the parameters, we need to numerically find the egg costs. Furthermore, this would need to be done continuously, as the mother’s reserve density may fluctuate over time as a result of variation in food availability and/or changes in assi

### 5. G:✅supports (r0.8) · C:✅supports (r0.9) · sim~0.80
*Source:* Pecquerie et al. - 2009 - Modeling fish growth and reproduction in the conte.pdf

> ontent. The energy content of an egg depended on the state of the female at the time of spawning. As stated by Kooijman (2000, 2009), we assumed that an offspring at birth would have the same scaledreservedensityas thefemaleat spawning;awell-fedfemalewould produce offsprings in good condition. Hence, the reserve at birth is given by Eb=ebVb[Em]=eφVb[Em] with the subscript b referring to birth, eb the scaled reserve density at birth,Vb the structural volume at birth (cm3) and eφ the scaled reserve density of the mother at spawning. Based on the assumption that the reserveand structuredynamics (Eqs.(A.1) and (A.2)) also apply to embryos in the absence of food intake, the routine ‘initial_scale

### 6. G:▫️neutral (r0.6) · C:❌contradicts (r0.9) · sim~0.80
*Source:* JageGous2023_suppinfo.pdf

> l support for this specific maternal effects rule as a general rule for all animals. As reviewed by Bernardo [5], there are species that follow this pattern, species that do the exact opposite (e.g., Daphnia magna, see [6]), and species in which egg size does not seem to respond at all to changes in the mother’s nutritional 6 [Page 7] status. The ‘stylised fact’ underlying this rule in stddeb [34] thus has plenty of exceptions. Furthermore, the review of Bernardo points at the large variation in egg size for the eggs produced by a single mother, even within a single clutch. Therefore, it is defensible to deviate from this rule in a stddeb-tktd implementation. This issue is dealt with in more

### 7. G:▫️neutral (r0.3) · C:▫️neutral (r0.4) · sim~0.80
*Source:* Lampert - 2025 - Daphnia magna.pdf

> the provisioning by their mother. Ebert (1993) reported a correlation (r2 = 0.884) between egg volume and neonate length. Lampert (1993) hatched 462 eggs in vitro and found a clear linear correlation (Fig. 12.4) between egg diameter (ED) and neonate length (NL). The regression was NL = 0.073 + 2.50 ED (r2 = 0.499). Similar relationships have been reported in other studies that measured egg diameter, volume, or mass. Hence, experts seem to agree on this fact. Consequently, in the laboratory it might be sufﬁcient to measure neonate size (or mass), while estimates of the eggs size would be more useful for preserved ﬁeld samples. Several studies investigated the factors respon- sible for the gen

### 8. G:✅supports (r0.7) · C:❌contradicts (r0.6) · sim~0.80
*Source:* SchlElln2001.pdf

> produce any eggs, and egg size should be small. At high food levels, egg size should also be small, but with the trend bounded by the minimum viable egg size. Thus egg size should be highest at intermediate food levels. This seems well supported by the data on Daphnia (e.g., Glazier 1992; Trubetskova and Lampert, 1995). It is not clear from the literature how much energy investment is required to confer resistance to starvation. The analysis is complicated by the different roles played by the lipid, protein, and carbohydrate parts of the diet. For Daphnia, we can guess that the energy needed FIG. 10. Effect of changing the length at hatching on the population dynamics at the minimum viable e

### 9. G:▫️neutral (r0.3) · C:▫️neutral (r0.3) · sim~0.79
*Source:* Lampert - 2025 - Daphnia magna.pdf

> henogenetic egg. Much interest has been shown in the relation- ship between the individual egg mass and the size (mass) of the neonate that hatches from the egg and is released from the mother’s brood pouch. As the mother does not nourish the eggs in the brood pouch, it is possible to remove eggs from the brood pouch by gentleﬂushing and let them develop individually in vi- tro. This way egg sizes can be related to neonate sizes individually. Due to metabolism, eggs must lose mass dur- ing the development of the embryo in the brood pouch. On average, Green (1956b) recorded 21 % loss of dry mass from ﬁrst egg stage to neonate release (chapt. 11). The phosphorus and carbon content of eggs and 

### 10. G:▫️neutral (r0.4) · C:▫️neutral (r0.4) · sim~0.79
*Source:* Lampert - 2025 - Daphnia magna.pdf

> SFR) depend on the rate of juvenile development and growth and the number of juvenile instars. During the last phase of egg development, the female must make a decision about the allocation of the total available energy to growth or reproduction. The amount invested into eggs is the ‘clutch mass’. Another decision is how to partition the clutch mass into individuals eggs (few large eggs or many small eggs). The number of eggs in an individual brood is the ‘clutch size’. The size of an individual egg is given as ‘egg mass’. Due to easier measurement and the almost spherical shape of a D. magna egg, egg sizes are often reported as volume or diameter. After neonates hatched from the brood pouch

### 11. G:✅supports (r0.7) · C:✅supports (r0.6) · sim~0.79
*Source:* Lampert - 2025 - Daphnia magna.pdf

> on D. magna offspring size. He also determined the inﬂuence of genotype, maternal age and size, and metabolic de- mands on this relationship, as well as the relationship between the investment per offspring (egg mass) and the total reproductive investment (brood mass). As expected, a high food ration resulted in much higher growth rates and larger body mass than a low food ra- tion. Hence, Glazier (1992) related the body mass to egg mass, brood mass and brood size. The coefﬁcients of these relationships are listed in Table 12.3 for high and low food and for two clones. The patterns of egg mass and brood size were similar, but there were strong genotype x environment interactions for egg mass

### 12. G:✅supports (r0.8) · C:✅supports (r0.9) · sim~0.79
*Source:* Zimm2013.pdf

> ext yet. 1.4. Maternal eﬀects Before scaling up to the population level, it is important to understand how the condition of the parents aﬀects the oﬀspring. This applies to toxic stress, but also to the nutritional status. In the standard DEB model, it is assumed that parents produce oﬀspring which have the same relative amount of reserve as themselves. Well-fed mothers produce large eggs, and the oﬀspring have an optimal reserve density. Poorly-fed mothers produce smaller eggs, and the oﬀspring have a less- than-optimal reserve density. This rule seems to apply to many species (Kooijman, 2010), but the opposite pat- tern has been observed as well. For example, it has been reported that some

### 13. G:✅supports (r0.8) · C:✅supports (r0.8) · sim~0.80
*Source:* Maternal effects and their consequences for offspring fitness in the Yellow Dung Fly (1999) — DOI https://doi.org/10.1046/j.1365-2435.1999.00269.x

> 1. Maternal adult diet and body size influence the fecundity of a female and possibly the quality and the performance of her offspring via egg size or egg quality. In laboratory experiments, negative effects in the offspring generation have often been obscured by optimal rearing conditions. 2. To estimate these effects in the Yellow Dung Fly, Scathophaga stercoraria , how maternal body size and adult nutritional status affected her fecundity, longevity and egg size were first investigated. 3. Second, it was investigated how female age and adult nutritional experience, mediated through the effects of egg size or egg quality, influenced the performance of offspring at different larval densitie

### 14. G:▫️neutral (r0.2) · C:▫️neutral (r0.2) · sim~0.79
*Source:* Ovarian reserve, female age and the chance for successful pregnancy. (2003)

> Both quantitative and qualitative factors regarding egg production are strong influences on IVF outcome. Markers of ovarian reserve such as basal FSH, clomiphene citrate challenge test (CCCT), and antral follicle counts are good predictors of the quantity of eggs which can be induced to grow. However, the quality of those eggs seems better predicted by the age of the women. In women past age 40, current success rates are low overall, even in those who good ovarian reserve who make many eggs; at this age, quantity does not make up for quality. By contrast, young women with limited ovarian reserve can have good success rates despite their limited cohort of eggs, because the eggs themselves are

### 15. G:▫️neutral (r0.4) · C:▫️neutral (r0.5) · sim~0.79
*Source:* Re‐examination of the capital and income dichotomy in breeding birds (1999) — DOI https://doi.org/10.1111/j.1474-919x.1999.tb04409.x

> During egg‐formation, energy and protein are deposited in the developing eggs but are, at the same time, needed by the laying female herself. This has been largely overlooked in the discussion on income and capital breeders (Drent &amp; Daan 1980, Thomas 1988). We discuss data on exogenous versus endogenous energy and nutrients used during egg‐formation for 12 well‐studied species ranging from the Adelie Penguin Pygoscelis adelie (3400 g) to the Blue Tit Parus caeruleus (11 g) and calculate which part of the total energy and nutrient requirements (of clutch and laying female) originates from direct food intake and/or from body reserves. Because energy and nutrients are also needed by the lay

### 16. G:▫️neutral (r0.5) · C:✅supports (r0.7) · sim~0.79
*Source:* Egg size, contents, and quality: maternal-age and -size effects on house fly eggs (2000) — DOI https://doi.org/10.1139/z00-086

> Egg size is generally regarded as a good predictor of egg quality. However, in phenotypic studies it is difficult to separate the effects of egg-size variation from the effects of the underlying cause of the differences in egg size. We examined the relationships between the size, shape, hatch rate, and biochemical and energy contents of house fly (Musca domestica L.) eggs using two distinct sources of egg-size variation: maternal age and maternal size. By comparing relationships among egg parameters between manipulations we were able to distinguish some maternal effects from pure egg-size effects. Maternal age was negatively correlated with clutch size, egg volume, hatch rate, and lipid cont

### 17. G:▫️neutral (r0.2) · C:▫️neutral (r0.2) · sim~0.78
*Source:* Gonadotropin-Releasing Hormone-Antagonist in Human In Vitro Fertilization (2006) — DOI https://doi.org/10.3109/9781420004960-6

> Both the quantity of eggs and their quality are strong influences on IVF outcome. Markers of ovarian reserve, such as basal follicle-stimulating hormone (FSH) and basal antral follicle (BAF) counts, are good predictors of the quantity of eggs which can be induced to grow. However, the quality of those eggs seems better predicted by the age of the women. In women past age 40, current success rates are low overall, even among those who make many eggs; at this age, quantity does not make up for quality. By contrast, young women with limited ovarian reserve can have good success rates despite their limited cohort of eggs, because the eggs themselves are of high quality; here quality matters more

### 18. G:✅supports (r0.8) · C:✅supports (r0.8) · sim~0.78
*Source:* Effects of Food, Genotype, and Maternal Size and Age on Offspring Investment in Daphnia Magna (1992) — DOI https://doi.org/10.2307/1940168

> This laboratory study of Daphnia magna had two major aims: (1) to examine the effect of food quantity on offspring size and number and how this effect varies with genotype and maternal size, age, and metabolic demand; and (2) to examine the relationship of investment per offspring to total reproductive investment. Differences in the response of offspring size to food quantity between the two clones in this study and between Daphnia studies in the literature are explained by nonlinear model that explicitly considers the effect of food quantity relative to the metabolic demands of the mother. According to this model, offspring size covaries positively with food quantity/maternal demand at very

### 19. G:✅supports (r0.8) · C:✅supports (r0.8) · sim~0.78
*Source:* Influence of Diet on Egg Size in American Coots (<i>Fulica americana</i>): Evidence from Food Supplementation and Biochemical Markers (2009) — DOI https://doi.org/10.1525/auk.2009.08197

> Food-supplementation studies on birds during egg laying have generally manipulated macronutrients and energy. Such studies have shown variable effects on egg size in American Coots (Fulica americana). We determined the relative influences of local environment, food quantity, and food quality on egg size in American Coots by supplementing food and carotenoids at three sites in Saskatchewan. Eggs were collected and analyzed for carotenoid content and stable isotopes (δ15N and δ13C) in the yolk to determine whether variation in the type of food eaten contributes to egg size. We also report on the isotopic analysis of American Coot tissues and their eggs to assess evidence of endogenous versus e

### 20. G:▫️neutral (r0.5) · C:▫️neutral (r0.5) · sim~0.78
*Source:* Interactions between lay date, clutch size, and postlaying energetic needs in a capital breeder (2010) — DOI https://doi.org/10.1093/beheco/arq189

> The condition-dependent model of optimal clutch size assumes body reserves required to initiate egg production include those for subsequent breeding phases. The threshold is expected to be similar among individuals, and hence postlaying condition should be independent of clutch size and lay date. Alternatively, the cost of incubation hypothesis predicts that females laying larger clutches should secure extra resources for incubation, and the expected fitness hypothesis suggests females adjust their condition according to the anticipated fitness benefits of the clutch. In these 2 cases, postlaying condition is predicted to be positively related to clutch size. We tested these predictions in c

### 21. G:▫️neutral (r0.4) · C:✅supports (r0.6) · sim~0.77
*Source:* Food Limitation And The Adaptive Significance Of Clutch Size In American Coots (fulica Americana) (1991)

> For many species of birds, egg formation costs are considered important constraints on timing of breeding, clutch size, and egg size. For American Coots (Fulica americana), body reserves and current food availability are both thought to affect these aspects of reproduction. In order to test the egg formation hypothesis, I conducted numerous observational and manipulative experiments on wild, free-ranging American Coots. Clutch size declined with laying date in five out of six years, contrary to seasonal patterns of food availability in prairie wetlands. Clutch size increased during two of three years in response to supplemental feeding. Laying date was only slightly affected by food suppleme

### 22. G:▫️neutral (r0.5) · C:❌contradicts (r0.6) · sim~0.77
*Source:* Factors Influencing Early Egg Size (1983) — DOI https://doi.org/10.3382/ps.0621155

> Three experiments were conducted to investigate the influence of diet composition and body weight on early egg size. Increasing dietary protein or methionine level had little or no effect on egg size for the first 12 weeks of production. Linoleic acid levels also failed to show any influence on egg size during a similar period of time. Body weight appeared to be the main factor influencing early egg size. It is postulated that the laying hen is producing at maximum capacity during the period of peak egg production and peak egg mass and, hence, is not capable of utilizing enhanced nutrient inputs to increase egg weight, which is similar to the situation often noted with older birds.

### 23. G:✅supports (r0.7) · C:✅supports (r0.8) · sim~0.77
*Source:* The Effect of Maternal State on the Steroid and Macronutrient Content of Lesser Black-Backed Gull Eggs (2010) — DOI https://doi.org/10.1086/656568

> It has been proposed that female birds can influence the phenotype of their offspring by provisioning eggs with variable amounts of nutrients and maternal hormones. Egg quality is strongly influenced by maternal body reserves and the amount of food available at the time of egg formation. This study investigated the effects of maternal state and food availability on the capacity of female lesser black-backed gulls Larus fuscus to provision their eggs with macronutrients and steroid hormones. Maternal state was reduced by increasing egg-production effort, whereas extra food was provided to reverse this effect. Compared with eggs of first clutches, eggs of experimentally induced replacement clu

### 24. G:▫️neutral (r0.4) · C:✅supports (r0.7) · sim~0.77
*Source:* Mothers reduce egg provisioning with age (2003) — DOI https://doi.org/10.1046/j.1461-0248.2003.00429.x

> Abstract Precise and comprehensive data on resource allocation into individual eggs are rare and this empirical void in the literature of life history strategies contrasts with the large number of theoretical studies. We show a marked decrease in reproductive investment in eggs with mother's age for egg size, sugar, protein, lipid and energy contents of eggs for a parasitic wasp. Egg size is a good predictor of offspring fitness, measured as survival of starving neonate larvae, but does not reveal possible biochemical changes. Lipids stabilize quickly at a minimal threshold while proteins and sugars decrease smoothly down to about 30% of the amount invested in the first egg. Because proteins

