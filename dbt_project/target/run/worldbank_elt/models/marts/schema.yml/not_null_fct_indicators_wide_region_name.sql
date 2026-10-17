
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select region_name
from "worldbank"."main"."fct_indicators_wide"
where region_name is null



  
  
      
    ) dbt_internal_test