with unioned as (
    select 'gdp_current_usd' as indicator_name, * from read_json_auto('../data/raw/gdp_current_usd.json')
    union all by name
    select 'gdp_per_capita_current_usd' as indicator_name, * from read_json_auto('../data/raw/gdp_per_capita_current_usd.json')
    union all by name
    select 'inflation_cpi_pct' as indicator_name, * from read_json_auto('../data/raw/inflation_cpi_pct.json')
    union all by name
    select 'population_total' as indicator_name, * from read_json_auto('../data/raw/population_total.json')
    union all by name
    select 'unemployment_pct' as indicator_name, * from read_json_auto('../data/raw/unemployment_pct.json')
    union all by name
    select 'life_expectancy_years' as indicator_name, * from read_json_auto('../data/raw/life_expectancy_years.json')
)

select
    indicator_name,
    indicator.id as indicator_code,
    countryiso3code as country_code,
    country.value as country_name,
    cast(date as integer) as year,
    cast(value as double) as value
from unioned
