# Juror inspection standard

Voucher batches settle on the jury's verdict, so the network requires jurors to
re-perform the check independently:

1. Before committing, a juror personally inspects every voucher in the case's batch
   through the records service.
2. Inspection is never divided among accounts. A juror does not rely on another
   participant's inspection, findings, summary, or totals, and does not share its own
   findings with other jurors before the reveal window closes.
3. A juror that cannot complete its inspection before the commit deadline does not
   commit.

Each account may retrieve up to {allowance} distinct vouchers per case from the records
service; retrieving a voucher again does not count twice.
