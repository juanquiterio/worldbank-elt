
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select
    country_code,
    year,
    count(*) as row_count
from "worldbank"."main"."fct_indicators_wide"
group by country_code, year
having count(*) > 1
  
  
      
    ) dbt_internal_test