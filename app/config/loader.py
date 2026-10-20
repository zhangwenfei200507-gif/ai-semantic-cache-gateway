import os
import yaml

from dotenv import load_dotenv


load_dotenv(
    "config/.env"
)



CONFIG_FILE = (
    "config/providers.yaml"
)



with open(
    CONFIG_FILE,
    "r",
    encoding="utf-8"
) as f:

    CONFIG = yaml.safe_load(f)



def get_all_providers():

    return CONFIG["providers"]




def get_provider(
    name
):


    provider = CONFIG["providers"].get(
        name
    )


    if provider is None:

        raise ValueError(
            f"Provider {name} not found"
        )


    api_env = provider.get(
        "api_key_env"
    )


    api_key = None


    if api_env:

        api_key = os.getenv(
            api_env
        )


    return {

        **provider,

        "api_key": api_key

    }