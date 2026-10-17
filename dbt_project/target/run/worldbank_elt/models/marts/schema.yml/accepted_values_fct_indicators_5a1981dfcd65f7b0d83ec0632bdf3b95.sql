
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        region_name as value_field,
        count(*) as n_records

    from "worldbank"."main"."fct_indicators_wide"
    group by region_name

)

select *
from all_values
where value_field not in (
    'East Asia & Pacific','Europe & Central Asia','Latin America & Caribbean','Middle East, North Africa, Afghanistan & Pakistan','North America','South Asia','Sub-Saharan Africa'
)



  
  
      
    ) dbt_internal_test