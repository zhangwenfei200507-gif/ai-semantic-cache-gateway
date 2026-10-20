from __future__ import annotations


from prometheus_client import (

    generate_latest,

    CONTENT_TYPE_LATEST,

)



def metrics_response():

    return (

        generate_latest(),

        CONTENT_TYPE_LATEST,

    )