select
    country_code,
    year,
    count(*) as row_count
from {{ ref('fct_indicators_wide') }}
group by country_code, year
having count(*) > 1
