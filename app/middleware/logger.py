import json
from datetime import datetime



class GatewayLogger:



    def log(

        self,

        data

    ):


        data["time"] = (
            datetime.now()
            .isoformat()
        )


        print(

            json.dumps(

                data,

                ensure_ascii=False

            )

        )



gateway_logger = GatewayLogger()