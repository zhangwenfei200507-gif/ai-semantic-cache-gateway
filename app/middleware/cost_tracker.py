class CostTracker:



    def __init__(self):

        self.total_tokens = 0

        self.total_cost = 0



    def record(

        self,

        tokens,

        cost

    ):


        self.total_tokens += tokens

        self.total_cost += cost



    def snapshot(self):


        return {


            "tokens":

                self.total_tokens,


            "cost":

                self.total_cost

        }



cost_tracker = CostTracker()