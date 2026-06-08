with src as (select * from {{ source('bronze', 'static_teams__Teams') }})
select
    cast(ID as bigint)            as team_id,
    cast(FULL_NAME as string)     as team_name,
    cast(ABBREVIATION as string)  as team_abbreviation,
    cast(NICKNAME as string)      as team_nickname,
    cast(CITY as string)          as team_city,
    cast(STATE as string)         as team_state,
    cast(YEAR_FOUNDED as int)     as year_founded
from src
