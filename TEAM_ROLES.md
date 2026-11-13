# Team roles — "Кибер 102" hackathon (КСТ Энерго Инжиниринг)

**Task:** prototype of a mobile AR assistant for an engineer inspecting industrial
equipment. It identifies the equipment, loads its digital card, runs a preliminary
AI visual analysis of components, calculates remaining service life, highlights
components needing attention over the camera image, and saves inspection results.

The work splits into three roles along the three natural seams of the system:
what the engineer sees (app + AR), what the AI decides (vision), and what the
system knows (data + calculations). Names are placeholders — assign by skills.

| | Role | Owns requirements |
|---|---|---|
| Member 1 | Mobile & AR developer | 4.1 (identification UI), 4.4, 4.6 (UI) |
| Member 2 | AI / computer vision engineer | 4.2 |
| Member 3 | Backend, data & digital twin — also team lead and presenter | 4.3, 4.5, 4.1 and 4.6 (server side), section 5 presentation |

---

## Member 1 — Mobile & AR developer

Owns everything the engineer touches on the phone or tablet.

- Camera screen and equipment identification: QR code / marking / serial number scan.
- Manual equipment selection when automatic recognition fails or is wrong.
- Equipment screen: model, composition, technical parameters, alarms on deviations.
- AR overlay on the live camera image: labels and frames on recognised components,
  status shown by colour and icon, short reason for the warning and recommended action.
- Tapping a component opens its detailed card: characteristics, service life,
  last maintenance date, recommended actions.
- Prompt that guides the engineer to point the camera at suspicious components
  (scenario step 5).
- Inspection forms: "component checked", record a defect or remark, register
  maintenance or replacement.

**Delivers:** the installable app that runs the full 10-step user scenario.

## Member 2 — AI / computer vision engineer

Owns the vision pipeline and the wording of its conclusions.

- Choose the 3–4 component types and the visual signs to support (the task
  explicitly allows limiting scope) — for example corrosion, leaks, mechanical damage.
- Collect and label the image set for the demo equipment.
- Component recognition: detect components in the frame and return their positions
  so Member 1 can draw the overlay.
- Defect detection and classification into exactly three categories:
  "no visible problems found", "inspection recommended",
  "signs of a possible defect found".
- Short explanation of the reason for each warning plus a recommendation for
  further checking; confidence score for each result.
- Match detected components to the entries in the equipment's digital card.
- Wording guard required by the task: the analysis is a preliminary inspection —
  "no visible defects" must never be presented as "equipment is healthy".

**Delivers:** an analysis service — image in; components, positions, category,
confidence, explanation out.

## Member 3 — Backend, data & digital twin (team lead, presenter)

Owns the data, the calculations, and the integration of the three parts.

- Database and digital card for each demo equipment sample: identifier, model,
  main characteristics, list of components, standard service life, installation and
  last replacement dates, inspection and maintenance history, previous results
  and recommendations.
- Realistic seed data, including current parameter values and setpoints, with a few
  deliberate deviations and overdue components so the demo has something to show.
- API for the app: look up equipment by QR / serial number, get card, get component,
  save inspection result.
- Service-life calculation: uses installation date, operating hours, work cycles
  and replacement history; flags components that are due or approaching the threshold.
- Keep three things separate in the data and in the API response: standard service
  life, calculated remaining life, and the result of the visual analysis. When data
  is insufficient for a reliable estimate, return that limitation explicitly.
- Combine the life calculation with Member 2's visual result into one status per
  component.
- Saving inspections, defects, maintenance and replacements into the equipment history.
- Integration, deployment of the demo, and the final presentation: architecture,
  technologies, limitations and risks, further development.

**Delivers:** running backend with seeded digital cards, and the pitch.

---

## Agree on this first (all three, before coding)

1. **Demo equipment** — one or two concrete samples everybody builds around.
2. **Component list** — the same component IDs are used in the database (Member 3),
   in the vision model's classes (Member 2) and in the overlay (Member 1).
3. **Two contracts** — the backend API (Member 1 ↔ Member 3) and the analysis
   response format (Member 2 ↔ Members 1 and 3). With these fixed, each member can
   work against mock data until the real parts are ready.
4. **Status scheme** — one set of colours and icons for the three AI categories and
   the service-life states.

## Requirement coverage

| Requirement | Member 1 | Member 2 | Member 3 |
|---|---|---|---|
| 4.1 Equipment identification | scan and manual selection UI | recognition by image (optional) | lookup, card, parameter deviations |
| 4.2 AI analysis of components | shows results | **owner** | supplies card data for matching |
| 4.3 Service-life calculation | shows results | — | **owner** |
| 4.4 AR visualisation | **owner** | supplies component positions | supplies statuses and texts |
| 4.5 Digital twin | card screens | — | **owner** |
| 4.6 Recording inspection results | forms | — | storage and history |
| 5. Presentation and architecture | app demo | AI section, limitations | **owner** |
