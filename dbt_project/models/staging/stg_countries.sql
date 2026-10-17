select
    id as country_code,
    name as country_name,
    trim(region.value) as region_name,
    region.id as region_code,
    incomeLevel.value as income_level,
    nullif(trim(capitalCity), '') as capital_city,
    region.id = 'NA' as is_aggregate
from read_json_auto('../data/raw/countries.json')
