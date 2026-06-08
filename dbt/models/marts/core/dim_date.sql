-- Contiguous calendar dimension covering all NBA seasons. Wide fixed bounds keep
-- it simple and future-proof; ~31k rows is negligible.
with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('1946-01-01' as date)",
        end_date="cast('2030-12-31' as date)"
    ) }}
)
select
    cast(date_format(date_day, 'yyyyMMdd') as int) as date_key,
    date_day                                       as full_date,
    year(date_day)                                 as year,
    month(date_day)                                as month,
    day(date_day)                                  as day_of_month,
    dayofweek(date_day)                            as day_of_week,
    date_format(date_day, 'EEEE')                  as day_name,
    weekofyear(date_day)                           as week_of_year,
    quarter(date_day)                              as quarter,
    case when dayofweek(date_day) in (1, 7) then true else false end as is_weekend
from spine
