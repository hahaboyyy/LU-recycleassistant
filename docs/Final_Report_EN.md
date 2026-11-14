LU Recycle Assistant

Photo based campus waste guidance

CDS521 group project report  15 November 2026

Team: ZYX, WJC, SY, WYR, ZXH and DZK

## Abstract

We developed a campus waste assistant that connects a photograph to a supported item and its disposal rule. A vision service supplies structured observations. A local decision module selects an audited rule, asks for missing identity information when needed, and accepts user correction. The application covers 16 item types and provides preparation steps and destinations. We evaluated a repaired version on the same 60 images used in an earlier run, with a direct model baseline and two rule-based settings. The repaired initial recognizer returned usable results for 60/60 images. Its photo-only item correctness on the 48 clear supported images was 42/48 (87.5%). The results support a bounded application demonstration while exposing remaining errors and limits of scripted interaction. This is a regression evaluation following repair, rather than an untouched external test.

## 1 Problem and AI rationale

A student may recognise a bottle or a sheet of paper but still be unsure how to dispose of it. Material, packaging type and the accepted collection route can change the advice. Lingnan University publishes campus waste information, while Hong Kong environmental guidance describes accepted materials and preparation [1,2]. Our goal is to help the user connect an everyday object to this information through a photograph.

A manual rule search is a useful alternative when a user already knows the item name. Visual AI helps when the user does not know the right search term. It can extract an object description and possible materials from the image, but some properties remain invisible. We therefore combine visual observations with a finite catalogue, explicit rules and short questions. The prototype focuses on one main object per photo, which keeps the task understandable and the advice traceable.

## 2 Related work and course concepts

CLIP demonstrates that image and text supervision can support transferable visual representations and classification through language descriptions [3]. LLaVA connects visual and language processing for instruction-following interactions [4]. These studies motivate the use of a vision-language interface: the application can request an English description and structured observations from an image. They are conceptual background, not an identification of the architecture behind our configured provider.

TACO provides images and annotations of litter in context and illustrates the difficulty of recognising waste outside clean product photographs [5]. Our materials retain per-image provenance, and the formal set includes uncertainty and unsupported objects. However, our evaluation is a small single-object application study, so its scores should not be compared directly with segmentation or detection results in TACO.

The implemented AI task is visual identification followed by constrained advice generation. It uses multimodal input, prompt instructions and output validation. Validation checks that data has the expected form; a correctly formatted answer can still describe the wrong object. The local rulebook controls the disposal instructions after an item is confirmed. This separation lets the team distinguish visual errors from decision errors and discuss the reliability of generated content.

## 3 System design and implementation

The application uses Python and Streamlit. Uploaded images are normalised with Pillow before being sent to the configured vision API. The prompt includes the supported catalogue, permitted fields and a compact JSON template. Pydantic validates the returned observation. The record contains an item ID or candidates, possible materials, visible state and image-quality information. Unknown values are allowed, and numeric self-reported confidence is not used to select a rule.

All modules share the same 16 item IDs. The catalogue resolver accepts known IDs and aliases, preserves unresolved candidates, and now treats a valid primary ID with conflicting structured candidates as ambiguous. This prevents a readable name from erasing uncertainty. The decision module then returns advice, a question, an out-of-scope message, a retake request or an unresolved result.

Each confirmed item selects a fixed disposal rule containing preparation, destination and sources. For example, plastic beverage bottles and glass beverage bottles use different rules. Preparation instructions are part of the returned advice. The rules do not branch on every visible residue field. Restricting this scope makes it possible to review why a particular instruction was selected.

Clarification asks about a distinguishing material or packaging type and stops after at most two rounds. User answers reuse the current recognition record. An explicit supported-item correction can replace a mistaken candidate, while a vague material answer does not automatically identify an object. A new photo starts a separate interaction history. The interface also provides correction, retry and restart controls.

Repair work increased the output allowance from the earlier experiment setting of 1200 tokens to 4096 and introduced a distinct output-limit error. A length-truncated response is not accepted as a completed answer, even when it contains partial JSON. The prompt now explains general distinctions between paper subtypes, cups, bottles and food-service cutlery. An eligible unresolved item category can receive one additional visual identity check, without reference labels or user answers. Different-material ambiguity still goes to user clarification. Additional calls and latency are included in the measured run. These changes address observed failure mechanisms; the evaluation does not isolate the effect of each individual change.

## 4 Evaluation design

The formal set contains 60 accepted E cases: 48 clear supported images, eight ambiguous images, three unsupported items and one unusable image. There are three clear images per supported item type. Twenty development examples are kept conceptually separate. The same formal images had already exposed weaknesses before repair, so the present results describe maintenance on this supplied set rather than independent generalisation to unseen campus photos. Image labels and source files were not changed after observing predictions.

Three primary settings use the same model configuration and image preprocessing: the direct baseline asks for identification and advice; the rule-based initial setting uses the first structured observation; the interactive setting reuses that observation and supplies the existing E answers in their original order, for at most two rounds. The interactive result is not another independent model sample and includes extra user information. Case order and baseline/improved order are shuffled with seed 521.

A separate by-key replay can supply an existing answer when the system asks a reasonable alternative question first. It does not invent answers for missing questions. This replay is reported separately from the primary fixed-order comparison. A protocol stop therefore remains distinct from an API failure and from an incorrect item prediction.

A further secondary simulation supplies a knowledgeable user answer only when the system asks a question. Existing E answers are used first; a missing answer for a supported item can use its accepted reference name. Those reference-informed answers enter the local decision module, not the vision API. This extension was designed after fixed-script stops were observed. It is a controlled simulation, not a real-user study or photo-only evidence. Confident wrong answers are not silently corrected.

The requested model ID is deepseek-v4-flash-vision-exp. The provider response records its served model label. Official documentation identifies this request ID as a legacy alias [6]. We retain both labels and the full safe request/response records instead of claiming that the request name proves the exact backend weights. The measured run uses 4096 output tokens, temperature zero, a 15-second read timeout and at most one transient transport retry. Hashes identify the source snapshot and exact processed image inputs.

Before the repaired run, the team acceptance threshold was set at 90%. We report two separate gates: usable initial recognition responses over all 60 images, and photo-only exact supported-item IDs over the 48 clear supported images. Errors and abstentions remain in these denominators. Advice correctness requires both the accepted route and required preparation. Baseline structured-ID accuracy is NA because its output is free text. Workflow-action correctness measures the chosen next step and is not image-identification accuracy.

## 5 Results and error analysis

| Measure | Direct model | Rules initial | Rules with user |
| --- | --- | --- | --- |
| Usable initial response | 60/60 (100.0%) | 60/60 (100.0%) | Shared initial |
| Photo-only item ID on 48 clear images | NA | 42/48 (87.5%) | Not photo-only |
| Complete advice on 48 clear images | 8/48 (16.7%) | 42/48 (87.5%) | 42/48 (87.5%) |
| Correct workflow action on all 60 | 48/60 (80.0%) | 51/60 (85.0%) | 53/60 (88.3%) |
| API or pipeline error cases | 0/60 | 0/60 | 0/60 |

The usable-response gate is PASS; the photo-only item gate is NOT MET. A returned answer is not automatically a correct identification, and a correct item can still produce an unsuitable next action. Complete-advice correctness on clear supported cases was 16.7% for the direct model and 87.5% for the initial integrated setting. These are the results of this run under a rule-specific rubric, not a universal recycling score.

The secondary reference-informed simulated-user replay identified 47/48 clear supported items correctly (97.9%), and 53/54 supported final items across clear and ambiguous cases (98.1%). Five cases received a newly supplied reference-name answer. This exceeds 90% under that assisted simulation, while the primary photo-only 42/48 result remains below 90%. The primary gates are not redefined by the secondary result. The difference shows the usefulness of identity confirmation under a knowledgeable-user assumption; it does not establish autonomous 90% accuracy.

The earlier run retained six empty length-limited enhanced responses. The repaired run is stored separately, with its own errors and timings. The combined repair includes a larger response allowance, clearer visual instructions and candidate handling. Network failures, wrong IDs, unexpected questions and scripted-answer stops remain visible in the per-case table. They are not removed to improve the percentage, and diagnostic retries do not replace primary rows.

The comparison supports checking local-rule consistency as well as recognising objects. The direct baseline does not receive the catalogue or local rulebook, so the observed difference combines these added resources and the decision process. It does not isolate a superior underlying visual model. Likewise, any assisted improvement must be attributed partly to additional user information. The separate flexible replay tests answer routing rather than new visual inference.

All primary non-identical advice responses are reviewed against the accepted reference with explicit reasons. Automated exact matches and assistant semantic assessments are labelled separately. Group members should review the semantic decisions and disputed cases before submission; this report does not claim independent student signoff. The current automated suite contains 177 pytest checks plus 11 backend checks. Those checks verify software behaviour, while the image experiment measures the configured service and application together.

## 6 Ethics limitations and next steps

Incorrect advice can contaminate recycling streams or send useful material to general waste. The interface therefore makes correction available, limits unsupported claims and offers retake or staff-check guidance when an item remains unresolved. Public collection information also needs checking against local signs and accepted materials at the time of disposal. Retaining rule sources supports review but does not prove that every collection point is unchanged.

Live photographs are transmitted to the configured provider. Users should avoid including faces, identity cards or other personal details. API credentials are kept outside tracked source files. The experiment preserves safe requests, image hashes and model outputs for reproducibility, so teams should also manage access to those records and set an appropriate retention period.

The study uses one provider configuration, three recorded repair iterations and a small supplied image set. It does not measure physical-camera capture, public-site latency, concurrent users or broad deployment reliability. Reusing the same images after repair can favour improvements specific to this collection. Future evaluation should include new campus photographs and real user answers, check material uncertainty, and assess the interface on the actual presentation devices.

The project contribution is an integrated application that joins visual observations to documented disposal rules and bounded user confirmation. The remaining engineering work is to review retained failures, validate the published live configuration and widen evaluation beyond the maintenance set. Claims in the presentation should use the exact denominators and distinguish response success, item correctness, advice correctness and interaction quality.

## Team contribution

| Member | Main contribution |
| --- | --- |
| ZYX | Supported items, disposal rules and development data |
| WJC | Visual recognition, API connection and direct baseline |
| SY | Decision logic and follow-up questions |
| WYR | Interface, user interaction and live demonstration |
| ZXH | Evaluation design, test references and result review |
| DZK | Integration, reproducibility and presentation coordination |

## References

[1] Lingnan University Office of Campus Development and Management. Waste Management and Collection of Recyclable Materials. https://www.ln.edu.hk/ocdm/sustainability/waste-management

[2] Hong Kong Environmental Protection Department. GREEN@COMMUNITY FAQ. https://www.wastereduction.gov.hk/en-hk/recycling-faq/greencommunity-faq

[3] Radford, A. et al. 2021. Learning Transferable Visual Models From Natural Language Supervision. https://arxiv.org/abs/2103.00020

[4] Liu, H., Li, C., Wu, Q. and Lee, Y. J. 2023. Visual Instruction Tuning. https://arxiv.org/abs/2304.08485

[5] Proenca, P. F. and Simoes, P. 2020. TACO Trash Annotations in Context for Litter Detection. https://arxiv.org/abs/2003.06975

[6] DeepSeek. API documentation Your First API Call. Accessed 15 November 2026. https://api-docs.deepseek.com/

[7] LU Recycle Assistant team. Source code and local frozen evaluation records, 15 November 2026. https://github.com/hahaboyyy/LU-recycleassistant

Reproducibility record: experimental configuration, source snapshot, dataset hashes, 180 primary case-arm rows, safe provider responses, semantic review reasons and separate flexible replay are retained in formal60_2026-11-15_release. The earlier run, first repair iteration (58/60 usable responses and 43/48 clear item IDs), and sandbox DNS-aborted attempt remain separately archived. The second iteration added one bounded transient retry and returned 60/60 usable outputs with 42/48 correct clear item IDs. The release iteration added one bounded visual identity review. All iterations remain archived.
