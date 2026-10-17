select
    country_code,
    year,
    count(*) as row_count
from "worldbank"."main"."fct_indicators_wide"
group by country_code, year
having count(*) > 1