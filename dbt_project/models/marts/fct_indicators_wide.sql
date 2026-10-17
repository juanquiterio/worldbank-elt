with indicators as (
    select * from {{ ref('stg_indicators') }}
),

countries as (
    select * from {{ ref('stg_countries') }}
    where not is_aggregate
),

pivoted as (
    select
        country_code,
        year,
        max(case when indicator_name = 'gdp_current_usd' then value end) as gdp_current_usd,
        max(case when indicator_name = 'gdp_per_capita_current_usd' then value end) as gdp_per_capita_current_usd,
        max(case when indicator_name = 'inflation_cpi_pct' then value end) as inflation_cpi_pct,
        max(case when indicator_name = 'population_total' then value end) as population_total,
        max(case when indicator_name = 'unemployment_pct' then value end) as unemployment_pct,
        max(case when indicator_name = 'life_expectancy_years' then value end) as life_expectancy_years
    from indicators
    group by country_code, year
)

select
    c.country_code,
    c.country_name,
    c.region_name,
    c.income_level,
    p.year,
    p.gdp_current_usd,
    p.gdp_per_capita_current_usd,
    p.inflation_cpi_pct,
    p.population_total,
    p.unemployment_pct,
    p.life_expectancy_years
from pivoted p
inner join countries c on p.country_code = c.country_code
