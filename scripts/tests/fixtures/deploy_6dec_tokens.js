/**
 * Deploy the two 6-decimal fixture tokens and fund the test parties.
 *
 * Driven by deploy_6dec_fixture.sh — run that, not this. It resolves the
 * account addresses from auth and passes them in, then registers the resulting
 * token/asset rows through the payments API.
 *
 * Prints one JSON object on stdout: { tokens: [{symbol, address, decimals}], funded: [...] }
 *
 * Requires NODE_PATH to point at yieldfabric-smart-contracts/node_modules and
 * cwd to be yieldfabric-smart-contracts (for the compiled artifact).
 */
const { ethers } = require('ethers');
const fs = require('fs');

const ARTIFACT = './artifacts/contracts/ConfidentialTreasury.sol/ConfidentialTreasury.json';
const DECIMALS = 6;
const TOTAL_SUPPLY = 10_000_000;        // constructor multiplies by 10^decimals
const FUND_PER_PARTY = 2_000_000n;      // whole tokens, each party, each token

const TOKENS = [
  { name: 'AUDF Test', symbol: 'AUDFT' },
  { name: 'USDC Test', symbol: 'USDCT' },
];

(async () => {
  const [rpc, accessControl, ...recipients] = process.argv.slice(2);
  if (!rpc || !accessControl || recipients.length === 0) {
    throw new Error('usage: deploy_6dec_tokens.js <rpc> <accessControl> <recipient...>');
  }

  const provider = new ethers.JsonRpcProvider(rpc);
  const chainId = (await provider.getNetwork()).chainId;
  if (chainId !== 31337n) {
    throw new Error(`refusing to deploy: this fixture is local-only, got chainId ${chainId}`);
  }

  const signer = await provider.getSigner(0);
  const artifact = JSON.parse(fs.readFileSync(ARTIFACT, 'utf8'));
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, signer);

  const out = { tokens: [], funded: [] };
  const unit = 10n ** BigInt(DECIMALS);

  for (const t of TOKENS) {
    const c = await factory.deploy(t.name, t.symbol, TOTAL_SUPPLY, DECIMALS, accessControl);
    await c.waitForDeployment();
    const address = await c.getAddress();

    const decimals = Number(await c.decimals());
    if (decimals !== DECIMALS) throw new Error(`${t.symbol} deployed with ${decimals} decimals`);

    for (const to of recipients) {
      await (await c.transfer(to, FUND_PER_PARTY * unit)).wait();
      out.funded.push({ symbol: t.symbol, to, balance: (await c.balanceOf(to)).toString() });
    }

    out.tokens.push({ symbol: t.symbol, name: t.name, address, decimals });
  }

  console.log(JSON.stringify(out, null, 2));
})();
