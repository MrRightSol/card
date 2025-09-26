# Synthetic Dataset Schema
txn_id, employee_id, merchant, city, category[Meal|Travel|Supplies|Transport|Lodging|Other],
timestamp(ISO), amount(float), channel[POS|Online], card_id,
is_weekend(int), hour(int), day_total(float), merchant_txn_7d(int), city_distance_km(float)