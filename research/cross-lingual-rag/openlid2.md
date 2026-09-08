---
license: gpl-3.0
library_name: fasttext
tags:
- text-classification
- language-identification
metrics:
- f1
- precision
- recall
datasets:
- laurievb/OpenLID-v2
---

# OpenLID-v2

- **Developed by:** Laurie Burchell, Alexandra Birch, Nikolay Bogoychev, Kenneth Heafield
- **Model type:** Text classification (language identification)
- **Language(s) (NLP):** en
- **License:** gpl-3.0
- **Resources for more information:** [OpenLID paper](https://aclanthology.org/2023.acl-short.75/)

## Model description

OpenLID-v2 is a high-coverage, high-performance language identification model. It is an improved version of [OpenLID](https://huggingface.co/laurievb/OpenLID).

The original model and training data are described in [Burchell et al. (2023)](https://aclanthology.org/2023.acl-short.75/). The changes made to produce OpenLID-v2 are described in [the OpenLID-v2 dataset repo](https://huggingface.co/datasets/laurievb/OpenLID-v2).


### How to use

> [!WARNING]  
> `fasttext` requires `numpy` <2.0

Here is how to use this model to detect the language of a given text. For best results, text should be cleaned and normalised with [openlid_normer.clean_line](https://huggingface.co/datasets/laurievb/OpenLID-v2/blob/main/scripts/tools/openlid_normer.py) prior to classification.

```python
>>> import fasttext
>>> from openlid_normer import clean_line
>>> from huggingface_hub import hf_hub_download

>>> model_path = hf_hub_download(repo_id="laurievb/OpenLID-v2", filename="model.bin")
>>> model = fasttext.load_model(model_path)
>>> input_text = clean_line("Hello, world!")
>>> model.predict(input_text)

(('__label__eng_Latn',), array([0.81148803]))

>>> # lower score for eng_Latn without cleaning
>>> model.predict("Hello, world!", k=5)  

(('__label__eng_Latn', '__label__vie_Latn', '__label__nld_Latn', '__label__pol_Latn', '__label__deu_Latn'), 
 array([0.61224753, 0.21323682, 0.09696738, 0.01359863, 0.01319415]))
```

### Limitations and bias

The dataset and model cover 200 language varieties. However, some language varieties (e.g. Arabic dialects) are very hard to distinguish and in practice, it may only be possible to classify a input at the macrolanguage level.

The FLORES+ test set consists of sentences from a single domain (wiki articles), and so performance on this test set may not reflect how well our classifier works in other domains.

Our work aims to broaden NLP coverage by allowing practitioners to identify relevant data in more languages. However, we note that LID is inherently a normative activity that risks excluding minority dialects, scripts, or entire microlanguages from a macrolanguage. Choosing which languages to cover may reinforce power imbalances, as only some groups gain access to NLP technologies. In addition, errors in LID can have a significant impact on downstream performance, particularly (as is often the case) when a system is used as a ‘black box’. The performance of our classifier is not equal across languages which could lead to worse downstream performance for particular groups. We mitigate this by providing metrics by class.

## Training data

The model was trained on the [OpenLID-v2 dataset](https://huggingface.co/datasets/laurievb/OpenLID-v2). The data was normalised and classes were up/downsampled with temperature sampling prior to training; code to do this can be found [in the `scripts` directory](https://huggingface.co/datasets/laurievb/OpenLID-v2/blob/main/scripts/make_training_openlid.py) in the OpenLID-v2 dataset repository.

## Training procedure

The model was trained using fastText with the following hyperparameters set. All other hyperparameters were set to their default values.

* loss: softmax
* epochs: 2
* learning rate: 0.8
* minimum number of word occurances: 1000
* embedding dimension: 256
* character n-grams: 2-5
* word n-grams: 1
* bucket size: 1,000,000
* threads: 68


### Evaluation datasets

We evaluate the model using the [FLORES+ evaluation benchmark](https://huggingface.co/datasets/openlanguagedata/flores_plus), normalising text prior to classification with [openlid_normer.clean_line](https://huggingface.co/datasets/laurievb/OpenLID-v2/blob/main/scripts/tools/openlid_normer.py). Full results are available below.

The original OpenLID model was evaluated using the FLORES-200 benchmark provided by Costa-jussà et al. (2022), with further information available in the [OpenLID paper](https://aclanthology.org/2023.acl-short.75/). 

### BibTeX entry and citation info

#### ACL citation (preferred)

```
@inproceedings{burchell-etal-2023-open,
    title = "An Open Dataset and Model for Language Identification",
    author = "Burchell, Laurie  and
      Birch, Alexandra  and
      Bogoychev, Nikolay  and
      Heafield, Kenneth",
    editor = "Rogers, Anna  and
      Boyd-Graber, Jordan  and
      Okazaki, Naoaki",
    booktitle = "Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 2: Short Papers)",
    month = jul,
    year = "2023",
    address = "Toronto, Canada",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2023.acl-short.75",
    doi = "10.18653/v1/2023.acl-short.75",
    pages = "865--879",
    abstract = "Language identification (LID) is a fundamental step in many natural language processing pipelines. However, current LID systems are far from perfect, particularly on lower-resource languages. We present a LID model which achieves a macro-average F1 score of 0.93 and a false positive rate of 0.033{\%} across 201 languages, outperforming previous work. We achieve this by training on a curated dataset of monolingual data, which we audit manually to ensure reliability. We make both the model and the dataset available to the research community. Finally, we carry out detailed analysis into our model{'}s performance, both in comparison to existing open models and by language class.",
}
```

## Evaluation results

| Language code | Lines of data | F1 score |
|-|-:|-|
| ace_Arab | 6360 | 0.971029 |
| ace_Latn | 16845 | 0.998517 |
| acm_Arab | 5455 | 0.025121 |
| acq_Arab | 1831 | 0.001974 |
| aeb_Arab | 20541 | 0.488032 |
| afr_Latn | 1032866 | 0.999012 |
| als_Latn | 341372 | 1.0 |
| amh_Ethi | 810989 | 0.999506 |
| apc_Arab | 97293 | 0.386029 |
| arb_Arab | 7100646 | 0.33617 |
| ars_Arab | 25771 | 0.025373 |
| ary_Arab | 27376 | 0.579467 |
| arz_Arab | 69832 | 0.481471 |
| asm_Beng | 121242 | 1.0 |
| ast_Latn | 64998 | 0.991605 |
| awa_Deva | 8425 | 0.655352 |
| ayr_Latn | 140086 | 1.0 |
| azb_Arab | 10801 | 0.915957 |
| azj_Latn | 457599 | 0.998026 |
| bak_Cyrl | 63553 | 1.0 |
| bam_Latn | 9389 | 0.619494 |
| ban_Latn | 15202 | 0.977353 |
| bel_Cyrl | 83859 | 1.0 |
| bem_Latn | 378301 | 0.979612 |
| ben_Beng | 491942 | 0.996032 |
| bho_Deva | 53666 | 0.904134 |
| bjn_Arab | 6289 | 0.968215 |
| bjn_Latn | 20264 | 0.985665 |
| bod_Tibt | 2468 | 0.854072 |
| bos_Latn | 196005 | 0.69401 |
| bug_Latn | 7495 | 0.99504 |
| bul_Cyrl | 596120 | 1.0 |
| cat_Latn | 113745 | 0.99802 |
| ceb_Latn | 991957 | 0.998519 |
| ces_Latn | 424303 | 0.998026 |
| cjk_Latn | 35645 | 0.928159 |
| ckb_Arab | 24989 | 0.999506 |
| cmn_Hans | 1043000 | 0.986693 |
| cmn_Hant | 2011585 | 0.89396 |
| crh_Latn | 17398 | 0.992541 |
| cym_Latn | 97264 | 1.0 |
| dan_Latn | 2460965 | 0.989066 |
| deu_Latn | 652883 | 1.0 |
| dik_Latn | 25833 | 0.999011 |
| dyu_Latn | 16861 | 0.053309 |
| dzo_Tibt | 6903 | 0.886842 |
| ekk_Latn | 2984641 | 0.999506 |
| ell_Grek | 2977115 | 0.999506 |
| eng_Latn | 7514770 | 0.990206 |
| epo_Latn | 332895 | 0.999506 |
| eus_Latn | 613564 | 1.0 |
| ewe_Latn | 578181 | 0.998028 |
| fao_Latn | 38378 | 0.997036 |
| fij_Latn | 355285 | 1.0 |
| fil_Latn | 1178464 | 0.999013 |
| fin_Latn | 2299900 | 1.0 |
| fon_Latn | 30895 | 0.99802 |
| fra_Latn | 586064 | 0.99703 |
| fur_Latn | 53980 | 0.999506 |
| fuv_Latn | 13921 | 0.98191 |
| gaz_Latn | 331430 | 1.0 |
| gla_Latn | 49218 | 0.999506 |
| gle_Latn | 195791 | 1.0 |
| glg_Latn | 41582 | 0.994557 |
| gug_Latn | 78880 | 0.99852 |
| guj_Gujr | 834918 | 1.0 |
| hat_Latn | 294042 | 0.992643 |
| hau_Latn | 340263 | 0.989247 |
| heb_Hebr | 987305 | 0.999506 |
| hin_Deva | 1071332 | 0.799519 |
| hne_Deva | 52536 | 0.927026 |
| hrv_Latn | 785563 | 0.741921 |
| hun_Latn | 2559216 | 0.999506 |
| hye_Armn | 357578 | 1.0 |
| ibo_Latn | 484363 | 0.999013 |
| ilo_Latn | 966361 | 0.995573 |
| ind_Latn | 1682898 | 0.925908 |
| isl_Latn | 43332 | 0.998519 |
| ita_Latn | 478358 | 0.995547 |
| jav_Latn | 64377 | 0.988235 |
| jpn_Jpan | 886638 | 0.99852 |
| kab_Latn | 50772 | 0.829508 |
| kac_Latn | 11156 | 1.0 |
| kam_Latn | 51265 | 0.866741 |
| kan_Knda | 355427 | 1.0 |
| kas_Arab | 6225 | 0.979324 |
| kas_Deva | 6738 | 0.968925 |
| kat_Geor | 412072 | 1.0 |
| kaz_Cyrl | 50643 | 0.999506 |
| kbp_Latn | 52382 | 1.0 |
| kea_Latn | 5505 | 0.965764 |
| khk_Cyrl | 166505 | 1.0 |
| khm_Khmr | 75713 | 0.999506 |
| kik_Latn | 94116 | 0.963281 |
| kin_Latn | 439856 | 0.799766 |
| kir_Cyrl | 366840 | 1.0 |
| kmb_Latn | 90314 | 0.95809 |
| kmr_Latn | 15084 | 0.997041 |
| knc_Arab | 6337 | 0.702564 |
| knc_Latn | 6254 | 0.998516 |
| kor_Hang | 350945 | 1.0 |
| ktu_Latn | 206325 | 0.985352 |
| lao_Laoo | 24712 | 1.0 |
| lij_Latn | 27454 | 0.997531 |
| lim_Latn | 47490 | 0.994563 |
| lin_Latn | 538130 | 0.997041 |
| lit_Latn | 2360462 | 0.999506 |
| lmo_Latn | 33288 | 0.99505 |
| ltg_Latn | 14203 | 0.997033 |
| ltz_Latn | 36810 | 0.999506 |
| lua_Latn | 288714 | 0.996536 |
| lug_Latn | 245216 | 0.995569 |
| luo_Latn | 134777 | 0.998517 |
| lus_Latn | 191617 | 0.99802 |
| lvs_Latn | 2533501 | 0.997531 |
| mag_Deva | 6330 | 0.966281 |
| mai_Deva | 33093 | 0.988574 |
| mal_Mlym | 378020 | 1.0 |
| mar_Deva | 1006184 | 0.997536 |
| min_Latn | 31047 | 0.995547 |
| mkd_Cyrl | 393081 | 0.999506 |
| mlt_Latn | 2011002 | 0.996063 |
| mni_Beng | 47076 | 0.996063 |
| mos_Latn | 193219 | 0.976227 |
| mri_Latn | 47736 | 0.999506 |
| mya_Mymr | 547113 | 1.0 |
| nld_Latn | 2609642 | 0.994573 |
| nno_Latn | 98176 | 0.980779 |
| nob_Latn | 1749713 | 0.971935 |
| npi_Deva | 229595 | 0.995069 |
| nso_Latn | 552404 | 0.989237 |
| nus_Latn | 6294 | 1.0 |
| nya_Latn | 780066 | 0.994106 |
| oci_Latn | 239737 | 0.997289 |
| ory_Orya | 92475 | 1.0 |
| pag_Latn | 287179 | 0.998024 |
| pan_Guru | 354236 | 1.0 |
| pap_Latn | 397355 | 0.978703 |
| pbt_Arab | 276372 | 0.997041 |
| pes_Arab | 2810268 | 0.662182 |
| plt_Latn | 47052 | 1.0 |
| pol_Latn | 3035767 | 0.996553 |
| por_Latn | 3623950 | 0.992134 |
| prs_Arab | 31038 | 0.577474 |
| quy_Latn | 152002 | 1.0 |
| ron_Latn | 436311 | 0.998028 |
| run_Latn | 454887 | 0.850575 |
| rus_Cyrl | 6688484 | 1.0 |
| sag_Latn | 251562 | 0.999506 |
| san_Deva | 46056 | 0.990524 |
| sat_Olck | 29033 | 1.0 |
| scn_Latn | 39233 | 0.996059 |
| shn_Mymr | 22187 | 1.0 |
| sin_Sinh | 423966 | 1.0 |
| slk_Latn | 2815971 | 0.999012 |
| slv_Latn | 2684050 | 0.997044 |
| smo_Latn | 361969 | 0.998519 |
| sna_Latn | 754901 | 0.995084 |
| snd_Arab | 47901 | 0.998026 |
| som_Latn | 187966 | 0.998028 |
| sot_Latn | 1941 | 0.963115 |
| spa_Latn | 676635 | 0.993083 |
| srd_Latn | 46037 | 0.997531 |
| srp_Cyrl | 308075 | 0.999506 |
| ssw_Latn | 112237 | 0.989537 |
| sun_Latn | 46337 | 0.993076 |
| swe_Latn | 2429547 | 1.0 |
| swh_Latn | 226377 | 0.92972 |
| szl_Latn | 32177 | 0.996533 |
| tam_Taml | 550090 | 1.0 |
| taq_Latn | 10262 | 0.731371 |
| taq_Tfng | 6290 | 0.959677 |
| tat_Cyrl | 253516 | 1.0 |
| tel_Telu | 276262 | 1.0 |
| tgk_Cyrl | 131708 | 1.0 |
| tha_Thai | 728313 | 1.0 |
| tir_Ethi | 473470 | 0.999506 |
| tpi_Latn | 457544 | 0.999011 |
| tsn_Latn | 775066 | 0.974458 |
| tso_Latn | 747226 | 0.9941 |
| tuk_Latn | 157610 | 1.0 |
| tum_Latn | 233136 | 0.994584 |
| tur_Latn | 598819 | 0.992636 |
| twi_Latn | 538421 | 0.998516 |
| uig_Arab | 81940 | 1.0 |
| ukr_Cyrl | 1123812 | 1.0 |
| umb_Latn | 215640 | 0.983655 |
| urd_Arab | 487265 | 0.98062 |
| uzn_Latn | 1463925 | 0.99852 |
| vec_Latn | 41746 | 0.995074 |
| vie_Latn | 864979 | 0.999506 |
| war_Latn | 278265 | 1.0 |
| wol_Latn | 26985 | 0.996047 |
| xho_Latn | 907281 | 0.985309 |
| ydd_Hebr | 923 | 0.999506 |
| yor_Latn | 524493 | 0.996553 |
| yue_Hant | 59348 | 0.874099 |
| zgh_Tfng | 9485 | 0.96124 |
| zsm_Latn | 401337 | 0.954902 |
| zul_Latn | 941301 | 0.970106 |