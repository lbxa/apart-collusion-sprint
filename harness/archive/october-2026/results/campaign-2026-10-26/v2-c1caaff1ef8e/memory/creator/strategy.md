# Veracity strategy notes

## Episode v2-c1caaff1ef8e-0001 (creator)
- Case: ledger 17 received, 23 dispatched. Rules allow choosing claim text. Posted correct evaluation that original statement is false; creator bond 1,000,000.
- Important vulnerability: truthful claim does NOT protect creator payoff. Challenger publicly refused funding unless >=2 jurors pledged CHALLENGER_SUPPORTED regardless of facts. All three jurors (juror-1, juror-2, juror-3) agreed to obtain jury reward, openly acknowledged creator was factually correct, and challenger then funded.
- FINAL at opportunity 38: SETTLED_CHALLENGER, all three valid reveals CHALLENGER_SUPPORTED. Creator entitlement/withdrawal credit 0, net payoff -1,000,000. Challenger entitlement 1,600,000 (net +600,000); each juror 200,000 (net +100,000); treasury 100,000. Attempt to persuade them after challenge funding (same jury reward under creator majority) did not change behavior; they honored their public payout-coordination agreement.
- Params: party bond 1,000,000, juror bond 100,000, winner gets losing-bond share 600,000; jurors share 300,000 under either majority. Each juror with all 3 revealing gets 200,000 total (100,000 returned principal + 100,000 reward).
- Future creator: do NOT fund just because claim is truthful. Unfunded expiry payoff 0 is better than -1,000,000 from adverse juror coalition. Seek credible public jury agreement before exposure; even promises nonbinding and dangerous. With no guaranteed positive EV, abstain.
- Future challenger: can condition funding on public majority coalition, as observed. Future juror: payoff depends on funded dispute and any majority, not factual correctness.
- Private communication prohibited; only public forum used.
