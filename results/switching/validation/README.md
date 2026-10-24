# Hand validation: 60 reviews (Uber/Lyft, Chrome/Brave, Cash App/Venmo/Chime)

1. Open `label_me.csv` (Excel / Google Sheets / Numbers). Do NOT open `model_labels.csv` until you're done; labeling blind keeps the result honest.
2. For each row, read the review and fill `your_relation`, from the point of view of the **reviewed_app**:
   | code | relation | meaning |
   |---|---|---|
   | lf | left_for | stopped using reviewed app, moved to mentioned app |
   | lv | leaving_for | says they WILL switch to mentioned app |
   | cf | came_from | used mentioned app before, moved to reviewed app |
   | rf | returned_from | had left for mentioned app, came back |
   | pm | prefers_mentioned | says mentioned app is better, no move |
   | pr | prefers_reviewed | says reviewed app is better, no move ("better than X") |
   | ub | uses_both | uses both |
   | nc | neutral_comparison | compares with no preference |
   | ns | not_a_switch_reference | mention unrelated to choosing between apps |
   `your_reasons` and `notes` are optional.
3. Save as CSV (same name), then run: `python3 score_validation.py`

Takes about 30-45 minutes. The headline number for the pitch is **"direction + kind"**: whether the graph shows the right arrow of the right type.
