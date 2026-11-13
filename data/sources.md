# Sources for Rules v1.0

| ID | Source | Use in this project |
| --- | --- | --- |
| `TACO_LABELS` | [TACO original annotations](https://github.com/pedropro/TACO/blob/master/data/annotations.json) and [dataset paper](https://arxiv.org/abs/2003.06975) | The annotation categories supplied candidate names. The English catalogue retains the original label for each item. The sources below support disposal routes. |
| `LU_RECYCLE` | [Lingnan University collection of recyclable materials](https://www.ln.edu.hk/ocdm/sustainability/waste-management/recycle) | Campus paper recycling and listed collection streams. Use the campus recycling map for bin locations. |
| `LU_SMART_BINS` | [Lingnan University waste management](https://www.ln.edu.hk/ocdm/sustainability/waste-management) | The university identifies metal, plastic bottle, and glass bottle smart bins on G/F of the Lau Lee Yuen Haan Amenities Building. |
| `LU_FOOD` | [Lingnan University food waste project](https://www.ln.edu.hk/lingnan-touch/136/bug-wars-against-food-waste-project-to-reduce-food-waste-on-campus-and-raise-public-awareness) | Confirms collection from student hostels and canteens. Ask canteen staff to identify the current collection point and accepted scraps. |
| `EPD_FAQ` | [Hong Kong EPD GREEN@COMMUNITY FAQ](https://www.wastereduction.gov.hk/en-hk/recycling-faq/greencommunity-faq) | Accepted material types and preparation. Community collection and campus collection are separate destinations. |
| `EPD_FOOD` | [Hong Kong EPD food waste recycling schemes](https://www.wastereduction.gov.hk/en-hk/waste-reduction-programme/food-waste-recycling-schemes) | Official information on designated Hong Kong food waste collection. |

Sources reviewed on 9 November 2026. Campus destinations rely on published university information. The prototype directs users to check current signs where acceptance depends on the specific bin or collection point.

## Photo provenance

The development set contains 10 TACO photos and 10 Wikimedia Commons photos. The case index records the source page, author, licence and any crop for each photo. TACO rows also record the original image and annotation IDs. The TACO annotation snapshot used for selection has SHA-256 `812c2e3f0d336b437f276597715de2abb08bb8a641599c45f593d233ec66457b`.

We used object annotations to focus each TACO photo on a main item and checked that the crop supported the expected action. We checked the licence on the original Flickr page for each selected TACO image and on the Commons file page for each supplemental image. Each photo remains subject to its recorded licence, including the ShareAlike terms for applicable crops.
