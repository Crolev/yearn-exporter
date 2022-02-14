If you want to add a new chain to the exporter, there are some things you'll need to do:

You must configure the network 

You must add the following constants:

- in ./yearn/networks.py:
- [ ] specify the chainid in the same way as the others.
- [ ] specify a network label in `Networks.label`.

- in ./yearn/constants.py:
- [ ] specify Treasury address. (if Yearn has a treasury contract deployed)
- [ ] specify Strategist Multisig address. (if Yearn has a SMS deployed)

- in ./yearn/prices/constants.py:
- [ ] add weth address to `tokens_by_network`.
- [ ] add usdc address to `tokens_by_network`.
- [ ] add dai address to `tokens_by_network`.
- [ ] configure `stablecoins` using popular + "safe" stablecoins on the chain.

- in ./yearn/multicall2.py:
- [ ] specify the appropriate multicall2 contract address.

- in ./yearn/prices/chainlink.py:
- [ ] specify any chainlink feeds available on the chain in `feeds`.
- [ ] specify the chainlink registry address in `registries` if applicable, or specify None if not applicable.

- in ./yearn/prices/uniswap/v2.py:
- [ ] specify the factory and router address for any important uni v2 forks on the chain.

- in ./yearn/utils.py:
- [ ] specify `BINARY_SEARCH_BARRIER` as 0 if all historical data is available. If historical data not available due to a network upgrade/etc, specify the first block of the available historical data.

- in ./yearn/middleware/middleware.py:
- [ ] specify `BATCH_SIZE` of approx 1 day based on avg block times on the chain.

- in ./scripts/historical-exporter.py:
- [ ] configure `end` to equal the date + hour of deployment for the first Yearn product on the chain.
- [ ] configure `data_query`. See `mapping` in ./yearn/outputs/victoria/output_helper.py to figure out the metric to specify based on what type of product was the first deployed on the chain.

- in ./scripts/historical-treasury-exporter.py:
- [ ] configure `end` to equal the date + hour of deployment for the Yearn Treasury on the chain.
- [ ] configure `data_query` using the existing networks as an example.

- in ./scripts/historical-sms-exporter.py:
- [ ] configure `end` to equal the date + hour of deployment for the Strategist Multisig on the chain.
- [ ] configure `data_query` using the existing networks as an example.


You also need to set up containers for each exporter on the new chain. This is a little more complicated but you can use existing containers as an example:
- [ ] define common envs for the chain
- [ ] add one new service entry for forwards exporter
- [ ] add one new service entry for historical exporter
- [ ] add one new service entry for treasury exporter
- [ ] add one new service entry for historical treasury exporter
- [ ] add one new service entry for sms exporter
- [ ] add one new service entry for historical sms exporter
- [ ] add one new service entry for wallet exporter
- [ ] add one new service entry for transactions exporter
- [ ] adapt entrypoint.sh


There still may be some things I'm missing, so its important to test to make sure everything works!

Once you've handled everything above, type `make all && make logs-all` into your terminal at the project root. The exporters will start running in docker and any exceptions will show in your terminal. If there are no exceptions, and everything appears to be running smoothly, it's time to submit your PR!