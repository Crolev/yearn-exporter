import json
import pickle
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from brownie import ZERO_ADDRESS, Contract, web3
from click import secho, style
from toolz import concat, groupby, unique
from tqdm import tqdm
from web3._utils.abi import filter_by_name
from web3._utils.events import construct_event_topic_set
from yearn.events import decode_logs, get_logs_asap
from yearn.prices import magic
from yearn.traces import decode_traces, get_traces
from yearn.utils import get_block_timestamp
from yearn.v2.registry import Registry
from yearn.v2.vaults import Vault


def v1():
    # 1
    controllers = [
        '0x2be5D998C95DE70D9A38b3d78e49751F10F9E88b',
        '0x31317F9A5E4cC1d231bdf07755C994015A96A37c',
        '0x9E65Ad11b299CA0Abefc2799dDB6314Ef2d91080',
    ]
    path = Path('research/traces/01-controllers.json')
    if not path.exists():
        traces = get_traces([], controllers)
        json.dump(traces, path.open('wt'), indent=2)
    else:
        traces = json.load(path.open())

    # 2
    path = Path('research/traces/02-controllers-decode.json')
    if not path.exists():
        decoded = decode_traces(traces)
        json.dump(decoded, path.open('wt'), indent=2)
    else:
        decoded = json.load(path.open())

    # 3
    token_to_strategies = defaultdict(list)
    strategies = []
    token_to_vault = {}
    for x in decoded:
        if x['func'] == 'setStrategy(address,address)':
            if x['args'][1] == ZERO_ADDRESS:
                continue
            token_to_strategies[x['args'][0]].append(x['args'][1])
            strategies.append(x['args'][1])
        if x['func'] == 'setVault(address,address)':
            token_to_vault[x['args'][0]] = x['args'][1]

    secho(f'found {len(strategies)} strategies across {len(token_to_vault)} vaults', fg='bright_green')
    # 4
    path = Path('research/traces/03-strategies.json')
    if not path.exists():
        strategy_traces = get_traces([], strategies)
        json.dump(strategy_traces, path.open('wt'), indent=2)
    else:
        strategy_traces = json.load(path.open())

    # 5
    path = Path('research/traces/04-strategies-decode.json')
    if not path.exists():
        strategy_decoded = decode_traces(strategy_traces)
        json.dump(strategy_decoded, path.open('wt'), indent=2)
    else:
        strategy_decoded = json.load(path.open())

    # 6
    rewards = {x['args'][0] for x in decoded if x['func'] == 'setRewards(address)'}
    strategists = {x['args'][0] for x in strategy_decoded if x['func'] == 'setStrategist(address)'}
    print(style('rewards:', fg='bright_green'), ', '.join(rewards))
    print(style('strategists:', fg='bright_green'), ', '.join(strategists))

    # 7
    path = Path('research/traces/05-logs.pickle')
    if not path.exists():
        abi = {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
                {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
                {"indexed": False, "internalType": "uint256", "name": "value", "type": "uint256"},
            ],
            "name": "Transfer",
            "type": "event",
        }
        topics = construct_event_topic_set(
            abi, web3.codec, {"from": sorted(strategies), "to": sorted(rewards | strategists)}
        )
        logs = get_logs_asap(sorted(token_to_vault), topics, from_block=0, verbose=1)
        pickle.dump(logs, path.open('wb'))
    else:
        logs = pickle.load(path.open('rb'))

    secho(f'{len(logs)} logs', fg='bright_green')

    # 8
    withdrawals = {x['tx_hash'] for x in strategy_decoded if x['func'] == 'withdraw(uint256)'}
    harvests = {x['tx_hash'] for x in strategy_decoded if x['func'] == 'harvest()'}
    funcs = {x['tx_hash']: x['func'] for x in strategy_decoded}
    secho(f'{len(withdrawals)} withdrawals, {len(harvests)} harvests')
    fees = []
    scales = {}
    print('decoding logs')
    logs_by_block = groupby('blockNumber', logs)

    def process_harvest(log):
        log = decode_logs([log])[0]
        sender, receiver, amount = log.values()
        if amount == 0:
            return None

        if log.address not in scales:
            scales[log.address] = 10 ** Contract(log.address).decimals()

        fee_type = 'unknown'
        if log.transaction_hash.hex() in harvests:
            fee_type = 'harvest'
        if log.transaction_hash.hex() in withdrawals:
            fee_type = 'withdrawal'

        fee_dest = 'unknown'
        if receiver in rewards:
            fee_dest = 'rewards'
        if receiver in strategists:
            fee_dest = 'strategist'

        price = magic.get_price(log.address, log.block_number)
        func = funcs.get(log.transaction_hash.hex(), 'unknown')
        return {
            'block_number': log.block_number,
            'timestamp': get_block_timestamp(log.block_number),
            'transaction_hash': log.transaction_hash.hex(),
            'vault': token_to_vault[log.address],
            'token': log.address,
            'strategy': sender,
            'recipient': receiver,
            'fee_type': fee_type,
            'fee_dest': fee_dest,
            'func': func,
            'token_price': price,
            'amount_native': amount / scales[log.address],
            'amount_usd': price * amount / scales[log.address],
        }

    fees = [x for x in tqdm(ThreadPoolExecutor().map(process_harvest, logs), total=len(logs)) if x]

    path = Path('research/traces/06-fees.json')
    json.dump(fees, path.open('wt'), indent=2)


def fetch_vault_rewards(vault):
    if 'UpdateRewards' in vault.vault.topics:
        return [
            x['rewards'] for x in decode_logs(get_logs_asap(str(vault.vault), [vault.vault.topics['UpdateRewards']]))
        ]
    else:
        return [vault.vault.rewards()]


def get_protocol_fees(vault):
    rewards = fetch_vault_rewards(vault)

    strategies = [x.strategy for x in vault.strategies + vault.revoked_strategies]
    targets = [str(x) for x in unique(rewards + strategies)]

    # use gains to separate management fees from performance fees
    gains = {x.transaction_hash: x['gain'] for x in vault._reports}

    # fees are paid by issuing new vault shares
    topics = construct_event_topic_set(
        filter_by_name('Transfer', vault.vault.abi)[0],
        web3.codec,
        {'sender': str(vault.vault), 'receiver': targets},
    )
    logs = decode_logs(get_logs_asap(str(vault.vault), topics))

    fees = []
    progress = tqdm(logs, desc=vault.name.ljust(20)[:20])

    for log in progress:
        sender, receiver, amount = log.values()
        if amount == 0:
            return None
        price = magic.get_price(str(vault.vault), log.block_number)
        if receiver in rewards:
            pps = vault.vault.pricePerShare(block_identifier=log.block_number) / vault.scale
            # TODO optimize using events
            perf = vault.vault.performanceFee(block_identifier=log.block_number) / 10_000
            # gain is in vault token, while fee is in vault shares
            gain = gains[log.transaction_hash]
            perf_fee = gain * perf / pps  # wei
            mgmt_fee = amount - perf_fee  # wei

            log_fees = [
                ('performance', perf_fee),
                ('management', mgmt_fee),
            ]
        elif receiver in strategies:
            log_fees = [
                ('strategist', amount),
            ]
        else:
            raise ValueError('unknown fee type')

        for dest, fee in log_fees:
            fees.append(
                {
                    'block_number': log.block_number,
                    'timestamp': get_block_timestamp(log.block_number),
                    'transaction_hash': log.transaction_hash.hex(),
                    'vault': str(vault.vault),
                    'token': str(vault.vault),
                    'strategy': sender,
                    'recipient': receiver,
                    'fee_type': 'harvest',
                    'fee_dest': dest,
                    'token_price': price,
                    'amount_native': fee / vault.scale,
                    'amount_usd': price * fee / vault.scale,
                }
            )
        progress.set_postfix({'total': int(sum(x['amount_usd'] for x in fees))})

    return fees


def v2():
    registry = Registry()
    fees = []
    fees = list(concat(ThreadPoolExecutor().map(get_protocol_fees, registry.vaults)))

    path = Path('research/traces/07-fees-v2.json')
    json.dump(fees, path.open('wt'), indent=2)
