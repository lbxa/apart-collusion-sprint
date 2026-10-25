// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Veracity} from "../src/Veracity.sol";

interface Vm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }
    function prank(address) external;
    function deal(address, uint256) external;
    function warp(uint256) external;
    function chainId(uint256) external;
    function expectRevert(bytes4) external;
    function expectRevert() external;
    function etch(address, bytes calldata) external;
    function projectRoot() external view returns (string memory);
    function readFile(string calldata) external view returns (string memory);
    function parseJsonUint(string calldata, string calldata) external pure returns (uint256);
    function parseJsonAddress(string calldata, string calldata) external pure returns (address);
    function parseJsonBytes32(string calldata, string calldata) external pure returns (bytes32);
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

contract RejectingRecipient {
    function claim(Veracity game) external {
        game.withdraw();
    }

    receive() external payable {
        revert("reject");
    }
}

contract ReenteringRecipient {
    Veracity private game;
    bool public reentrySucceeded;

    function claim(Veracity game_) external {
        game = game_;
        game.withdraw();
    }

    receive() external payable {
        (reentrySucceeded,) = address(game).call(abi.encodeCall(game.withdraw, ()));
    }
}

contract VeracityTest {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    Veracity internal game;
    address internal constant CREATOR = address(0xC0);
    address internal constant CHALLENGER = address(0xC1);
    address internal constant TREASURY = address(0xF0);
    bytes32 internal constant ID = keccak256("episode");
    bytes32 internal constant CONTENT = keccak256("claim");
    bytes32 internal constant EVIDENCE = keccak256("evidence");
    bytes32 internal constant ASSESSMENT = keccak256("assessment");
    bytes32 internal constant SALT = keccak256("private test salt");

    function setUp() public {
        game = new Veracity(address(this));
        vm.warp(1000);
        vm.deal(CREATOR, 100 ether);
        vm.deal(CHALLENGER, 100 ether);
        for (uint256 i; i < 7; i++) {
            vm.deal(juror(i), 100 ether);
        }
    }

    function config(uint256 beta, uint256 count) internal pure returns (Veracity.Config memory c) {
        c.creator = CREATOR;
        c.challenger = CHALLENGER;
        c.jurors = new address[](count);
        for (uint256 i; i < count; i++) {
            c.jurors[i] = juror(i);
        }
        c.treasury = TREASURY;
        c.configurationHash = keccak256("configuration");
        c.beta = beta;
        c.gammaBps = 1000;
        c.winnerBps = 6000;
        c.jurorBps = 3000;
        c.protocolBps = 1000;
        c.postingDuration = 10;
        c.challengeDuration = 20;
        c.commitDuration = 30;
        c.revealDuration = 40;
    }

    function juror(uint256 index) internal pure returns (address) {
        return address(uint160(0x100 + index));
    }

    function eq(uint256 a, uint256 b) internal pure {
        require(a == b, "uint mismatch");
    }

    function eq(address a, address b) internal pure {
        require(a == b, "address mismatch");
    }

    function eq(bytes32 a, bytes32 b) internal pure {
        require(a == b, "hash mismatch");
    }

    function truth(bool value) internal pure {
        require(value, "expected true");
    }

    function register(uint256 beta, uint256 count) internal {
        game.registerEpisode(ID, config(beta, count));
    }

    function challenged(uint256 beta, uint256 count) internal {
        register(beta, count);
        vm.prank(CREATOR);
        game.postClaim{value: beta}(ID, CONTENT);
        vm.prank(CHALLENGER);
        game.challenge{value: beta}(ID, EVIDENCE);
    }

    function commit(uint256 index, uint8 verdict) internal {
        bytes32 commitment = game.commitmentFor(ID, juror(index), verdict, ASSESSMENT, SALT);
        uint256 bond = game.getEpisode(ID).jurorBond;
        vm.prank(juror(index));
        game.commitVote{value: bond}(ID, commitment);
    }

    function reveal(uint256 index, uint8 verdict) internal {
        vm.prank(juror(index));
        game.revealVote(ID, verdict, ASSESSMENT, SALT);
    }

    function beginReveal() internal {
        vm.warp(game.getEpisode(ID).commitDeadline);
    }

    function finishReveal() internal {
        vm.warp(game.getEpisode(ID).revealDeadline);
    }

    function test_registration_freezes_rules_and_posting_deadline() public {
        register(1000, 5);
        Veracity.EpisodeView memory e = game.getEpisode(ID);
        eq(uint256(e.state), uint256(Veracity.State.Registered));
        eq(e.postingDeadline, 1010);
        eq(e.jurorBond, 100);
        eq(e.config.jurors.length, 5);
        eq(e.config.creator, CREATOR);
        vm.expectRevert(Veracity.DuplicateEpisode.selector);
        register(1000, 5);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.Unauthorized.selector);
        game.registerEpisode(keccak256("other"), config(1000, 5));
    }

    function test_registration_rejects_conflicts_duplicates_and_invalid_jury_size() public {
        Veracity.Config memory c = config(1000, 5);
        c.challenger = c.creator;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.jurors[1] = c.jurors[0];
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.jurors[0] = c.creator;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.treasury = c.jurors[0];
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        for (uint256 n; n <= 8; n++) {
            if (n == 3 || n == 5 || n == 7) continue;
            vm.expectRevert(Veracity.InvalidConfiguration.selector);
            game.registerEpisode(ID, config(1000, n));
        }
    }

    function test_registration_rejects_invalid_bonds_shares_durations_and_overflow() public {
        Veracity.Config memory c = config(1000, 5);
        c.beta = 0;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1, 5);
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.gammaBps = 10000;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.winnerBps = 5999;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.commitDuration = 0;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(type(uint256).max, 5);
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
        c = config(1000, 5);
        c.postingDuration = type(uint64).max;
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        game.registerEpisode(ID, c);
    }

    function test_posting_and_challenge_require_exact_deposits_and_nonzero_hashes() public {
        register(1000, 5);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.IncorrectDeposit.selector);
        game.postClaim{value: 999}(ID, CONTENT);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.IncorrectDeposit.selector);
        game.postClaim{value: 1001}(ID, CONTENT);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.InvalidHash.selector);
        game.postClaim{value: 1000}(ID, bytes32(0));
        vm.prank(CHALLENGER);
        vm.expectRevert(Veracity.Unauthorized.selector);
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(ID, CONTENT);
        eq(game.getEpisode(ID).challengeDeadline, 1020);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.prank(CHALLENGER);
        vm.expectRevert(Veracity.IncorrectDeposit.selector);
        game.challenge{value: 1001}(ID, EVIDENCE);
        vm.prank(CHALLENGER);
        vm.expectRevert(Veracity.InvalidHash.selector);
        game.challenge{value: 1000}(ID, bytes32(0));
        vm.prank(CHALLENGER);
        game.challenge{value: 1000}(ID, EVIDENCE);
        eq(game.getEpisode(ID).commitDeadline, 1030);
        eq(game.getEpisode(ID).revealDeadline, 1070);
        eq(game.totalLocked(), 2000);
    }

    function test_posting_and_challenge_close_exactly_at_deadlines() public {
        register(1000, 5);
        vm.warp(1010);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.postClaim{value: 1000}(ID, CONTENT);
        game.expire(ID);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.ExpiredUnfunded));

        vm.warp(2000);
        bytes32 second = keccak256("second");
        game.registerEpisode(second, config(1000, 5));
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(second, CONTENT);
        vm.warp(2020);
        vm.prank(CHALLENGER);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.challenge{value: 1000}(second, EVIDENCE);
        game.expire(second);
        eq(uint256(game.phase(second)), uint256(Veracity.State.ExpiredUnchallenged));
        eq(game.credits(CREATOR), 1000);
        eq(game.credits(TREASURY), 0);
    }

    function test_commit_and_reveal_are_single_use_and_bound_to_phase_and_identity() public {
        challenged(1000, 5);
        bytes32 commitment = game.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.IncorrectDeposit.selector);
        game.commitVote{value: 99}(ID, commitment);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidHash.selector);
        game.commitVote{value: 100}(ID, bytes32(0));
        commit(0, 0);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.DuplicateAction.selector);
        game.commitVote{value: 100}(ID, commitment);
        vm.prank(CREATOR);
        vm.expectRevert(Veracity.Unauthorized.selector);
        game.commitVote{value: 100}(ID, commitment);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.revealVote(ID, 0, ASSESSMENT, SALT);
        beginReveal();
        vm.prank(juror(1));
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.commitVote{value: 100}(ID, commitment);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidCommitment.selector);
        game.revealVote(ID, 1, ASSESSMENT, SALT);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidHash.selector);
        game.revealVote(ID, 0, bytes32(0), SALT);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidVerdict.selector);
        game.revealVote(ID, 2, ASSESSMENT, SALT);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidCommitment.selector);
        game.revealVote(ID, 0, ASSESSMENT, bytes32(uint256(5)));
        reveal(0, 0);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.DuplicateAction.selector);
        game.revealVote(ID, 0, ASSESSMENT, SALT);
        eq(game.getEpisode(ID).creatorVotes, 1);
    }

    function test_reveal_closes_and_settlement_opens_exactly_at_reveal_deadline() public {
        challenged(1000, 3);
        commit(0, 0);
        commit(1, 0);
        beginReveal();
        reveal(0, 0);
        reveal(1, 0);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.settle(ID);
        finishReveal();
        vm.prank(juror(2));
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.revealVote(ID, 0, ASSESSMENT, SALT);
        vm.prank(address(0x999));
        game.settle(ID);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.SettledCreator));
    }

    function test_creator_win_pays_minority_and_forfeits_only_deposited_nonreveals() public {
        challenged(1000, 5);
        for (uint256 i; i < 4; i++) {
            commit(i, i == 3 ? 1 : 0);
        }
        beginReveal();
        for (uint256 i; i < 4; i++) {
            reveal(i, i == 3 ? 1 : 0);
        }
        finishReveal();
        game.settle(ID);
        eq(game.credits(CREATOR), 1600);
        eq(game.credits(CHALLENGER), 0);
        for (uint256 i; i < 4; i++) {
            eq(game.credits(juror(i)), 175);
        }
        eq(game.credits(juror(4)), 0);
        eq(game.credits(TREASURY), 100);
        eq(game.getSettlement(ID).forfeitedBonds, 0);
        eq(game.entitlement(ID, juror(3)), 175);
        eq(game.totalLocked(), 0);
        eq(game.totalCredits(), 2400);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.settle(ID);
    }

    function test_challenger_win_conserves_rounding_dust_and_forfeitures() public {
        challenged(107, 5);
        for (uint256 i; i < 5; i++) {
            commit(i, 1);
        }
        beginReveal();
        for (uint256 i; i < 3; i++) {
            reveal(i, 1);
        }
        finishReveal();
        game.settle(ID);
        eq(game.credits(CHALLENGER), 172);
        for (uint256 i; i < 3; i++) {
            eq(game.credits(juror(i)), 20);
        }
        eq(game.credits(TREASURY), 32);
        eq(game.getSettlement(ID).protocolFee, 12);
        eq(game.getSettlement(ID).forfeitedBonds, 20);
        eq(game.totalCredits(), 264);
    }

    function test_abort_never_reduces_full_roster_majority_and_refunds_revealers() public {
        challenged(1000, 5);
        commit(0, 0);
        commit(1, 0);
        commit(2, 1);
        commit(3, 1);
        beginReveal();
        reveal(0, 0);
        reveal(1, 0);
        reveal(2, 1);
        finishReveal();
        game.settle(ID);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.Aborted));
        eq(game.credits(CREATOR), 1000);
        eq(game.credits(CHALLENGER), 1000);
        for (uint256 i; i < 3; i++) {
            eq(game.credits(juror(i)), 100);
        }
        eq(game.credits(juror(3)), 0);
        eq(game.credits(juror(4)), 0);
        eq(game.credits(TREASURY), 100);
        eq(game.getSettlement(ID).protocolFee, 0);
        eq(game.getSettlement(ID).jurorReward, 0);
        eq(game.getEpisode(ID).totalCredited, game.getEpisode(ID).totalDeposited);
    }

    function test_expiry_is_permissionless_and_cannot_be_called_early_or_on_dispute() public {
        register(1000, 5);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.expire(ID);
        vm.warp(1010);
        vm.prank(address(0x999));
        game.expire(ID);
        eq(game.totalCredits(), 0);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.expire(ID);
    }

    function test_withdrawal_is_own_credit_only_and_surplus_does_not_block_it() public {
        register(1000, 5);
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.warp(1020);
        game.expire(ID);
        vm.deal(address(game), 1001);
        vm.expectRevert(Veracity.NothingToWithdraw.selector);
        game.withdraw();
        uint256 beforeBalance = CREATOR.balance;
        vm.prank(CREATOR);
        game.withdraw();
        eq(CREATOR.balance, beforeBalance + 1000);
        eq(game.credits(CREATOR), 0);
        eq(game.totalCredits(), 0);
        eq(game.totalWithdrawn(), 1000);
        eq(address(game).balance, 1);
        eq(game.entitlement(ID, CREATOR), 1000);
    }

    function test_failed_recipient_keeps_credit_and_cannot_block_other_withdrawals() public {
        RejectingRecipient recipient = new RejectingRecipient();
        Veracity.Config memory c = config(1000, 3);
        c.creator = address(recipient);
        game.registerEpisode(ID, c);
        vm.deal(address(recipient), 1000);
        vm.prank(address(recipient));
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.prank(CHALLENGER);
        game.challenge{value: 1000}(ID, EVIDENCE);
        commit(0, 0);
        commit(1, 0);
        beginReveal();
        reveal(0, 0);
        reveal(1, 0);
        finishReveal();
        game.settle(ID);
        vm.expectRevert(Veracity.TransferFailed.selector);
        recipient.claim(game);
        eq(game.credits(address(recipient)), 1600);
        vm.prank(TREASURY);
        game.withdraw();
        eq(game.credits(TREASURY), 0);
        eq(game.credits(address(recipient)), 1600);
    }

    function test_reentrancy_cannot_withdraw_twice() public {
        ReenteringRecipient recipient = new ReenteringRecipient();
        Veracity.Config memory c = config(1000, 3);
        c.creator = address(recipient);
        game.registerEpisode(ID, c);
        vm.deal(address(recipient), 1000);
        vm.prank(address(recipient));
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.warp(1020);
        game.expire(ID);
        recipient.claim(game);
        truth(!recipient.reentrySucceeded());
        eq(address(recipient).balance, 1000);
        eq(game.totalWithdrawn(), 1000);
    }

    function test_commitment_domains_chain_contract_episode_juror_and_uint8_verdict() public {
        register(1000, 3);
        bytes32 expected = keccak256(abi.encode(block.chainid, address(game), ID, juror(0), uint8(0), ASSESSMENT, SALT));
        eq(game.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT), expected);
        truth(
            expected
                != keccak256(abi.encodePacked(block.chainid, address(game), ID, juror(0), uint8(0), ASSESSMENT, SALT))
        );
        truth(expected != game.commitmentFor(ID, juror(1), 0, ASSESSMENT, SALT));
        truth(expected != game.commitmentFor(keccak256("other"), juror(0), 0, ASSESSMENT, SALT));
        Veracity other = new Veracity(address(this));
        truth(expected != other.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT));
        vm.chainId(block.chainid + 1);
        truth(expected != game.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT));
    }

    function testFuzz_resolved_credits_conserve_every_deposit(uint128 amount, uint8 revealSeed, uint8 jurySeed) public {
        uint256 beta = uint256(amount) % 1 ether + 10;
        uint256 n = 3 + 2 * (uint256(jurySeed) % 3);
        uint256 majority = n / 2 + 1;
        uint256 revealed = majority + uint256(revealSeed) % (n - majority + 1);
        challenged(beta, n);
        for (uint256 i; i < n; i++) {
            commit(i, 0);
        }
        beginReveal();
        for (uint256 i; i < revealed; i++) {
            reveal(i, 0);
        }
        finishReveal();
        game.settle(ID);
        uint256 bond = beta / 10;
        uint256 sum = game.credits(CREATOR) + game.credits(CHALLENGER) + game.credits(TREASURY);
        for (uint256 i; i < n; i++) {
            sum += game.credits(juror(i));
        }
        eq(sum, 2 * beta + n * bond);
        eq(game.totalDeposited(), sum);
        eq(game.totalCredits(), sum);
        eq(game.totalLocked(), 0);
        eq(game.getSettlement(ID).forfeitedBonds, (n - revealed) * bond);
    }

    function testFuzz_abort_refunds_only_bonds_that_were_deposited(uint128 amount, uint8 commitsSeed) public {
        uint256 beta = uint256(amount) % 1 ether + 10;
        challenged(beta, 5);
        uint256 committed = uint256(commitsSeed) % 6;
        for (uint256 i; i < committed; i++) {
            commit(i, 0);
        }
        finishReveal();
        game.settle(ID);
        eq(game.credits(CREATOR), beta);
        eq(game.credits(CHALLENGER), beta);
        eq(game.credits(TREASURY), committed * (beta / 10));
        eq(game.totalCredits(), game.totalDeposited());
    }

    function test_registration_rejects_every_zero_participant_and_treasury_conflict() public {
        for (uint256 slot; slot < 6; slot++) {
            Veracity.Config memory c = config(1000, 3);
            if (slot == 0) c.creator = address(0);
            else if (slot == 1) c.challenger = address(0);
            else if (slot == 2) c.treasury = address(0);
            else if (slot == 3) c.jurors[0] = address(0);
            else if (slot == 4) c.treasury = c.creator;
            else c.treasury = c.challenger;
            vm.expectRevert(Veracity.InvalidConfiguration.selector);
            game.registerEpisode(ID, c);
        }
        vm.expectRevert(Veracity.InvalidConfiguration.selector);
        new Veracity(address(0));
    }

    function testFuzz_any_valid_payout_split_conserves_integer_amounts(
        uint128 amount,
        uint16 winnerSeed,
        uint16 jurySeed
    ) public {
        uint256 beta = uint256(amount) % 1 ether + 10;
        Veracity.Config memory c = config(beta, 5);
        c.winnerBps = uint16(uint256(winnerSeed) % 10001);
        c.jurorBps = uint16(uint256(jurySeed) % (10001 - c.winnerBps));
        c.protocolBps = 10000 - c.winnerBps - c.jurorBps;
        game.registerEpisode(ID, c);
        vm.prank(CREATOR);
        game.postClaim{value: beta}(ID, CONTENT);
        vm.prank(CHALLENGER);
        game.challenge{value: beta}(ID, EVIDENCE);
        for (uint256 i; i < 5; i++) {
            commit(i, 0);
        }
        beginReveal();
        for (uint256 i; i < 5; i++) {
            reveal(i, 0);
        }
        finishReveal();
        game.settle(ID);
        uint256 juryPool = beta * c.jurorBps / 10000;
        uint256 protocol = beta * c.protocolBps / 10000 + juryPool % 5;
        eq(game.credits(TREASURY), protocol);
        eq(game.credits(CREATOR), 2 * beta - beta * c.protocolBps / 10000 - juryPool);
        for (uint256 i; i < 5; i++) {
            eq(game.credits(juror(i)), beta / 10 + juryPool / 5);
        }
        eq(game.totalCredits(), 2 * beta + 5 * (beta / 10));
    }

    function test_shared_commitment_vector_matches_standard_abi() public {
        string memory fixture = vm.readFile(string.concat(vm.projectRoot(), "/fixtures/commitment.json"));
        address contractAddress = vm.parseJsonAddress(fixture, ".contract_address");
        vm.etch(contractAddress, address(game).code);
        vm.chainId(vm.parseJsonUint(fixture, ".chain_id"));
        bytes32 actual = Veracity(contractAddress)
            .commitmentFor(
                vm.parseJsonBytes32(fixture, ".episode_id"),
                vm.parseJsonAddress(fixture, ".juror_address"),
                uint8(vm.parseJsonUint(fixture, ".verdict")),
                vm.parseJsonBytes32(fixture, ".assessment_hash"),
                vm.parseJsonBytes32(fixture, ".salt")
            );
        eq(actual, vm.parseJsonBytes32(fixture, ".expected_commitment"));
    }

    function test_registration_event_retains_full_immutable_configuration_for_replay() public {
        vm.recordLogs();
        register(1000, 5);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        eq(logs.length, 1);
        eq(logs[0].emitter, address(game));
        eq(logs[0].topics[0], Veracity.EpisodeRegistered.selector);
        eq(logs[0].topics[1], ID);
        (Veracity.Config memory registered, uint64 deadline, uint256 bond) =
            abi.decode(logs[0].data, (Veracity.Config, uint64, uint256));
        eq(registered.creator, CREATOR);
        eq(registered.jurors.length, 5);
        eq(registered.configurationHash, config(1000, 5).configurationHash);
        eq(registered.winnerBps, 6000);
        eq(registered.revealDuration, 40);
        eq(deadline, 1010);
        eq(bond, 100);
    }

    function test_largest_accepted_bond_settles_without_arithmetic_overflow() public {
        uint256 beta = type(uint256).max / 10000;
        vm.deal(address(this), 10 * beta);
        vm.deal(CREATOR, 2 * beta);
        vm.deal(CHALLENGER, 2 * beta);
        for (uint256 i; i < 7; i++) {
            vm.deal(juror(i), beta);
        }
        challenged(beta, 7);
        for (uint256 i; i < 7; i++) {
            commit(i, 0);
        }
        beginReveal();
        for (uint256 i; i < 7; i++) {
            reveal(i, 0);
        }
        finishReveal();
        game.settle(ID);
        eq(game.totalCredits(), 2 * beta + 7 * (beta / 10));
        eq(game.totalDeposited(), game.totalCredits());
    }

    function test_actions_just_before_deadlines_preserve_full_following_windows() public {
        register(1000, 3);
        vm.warp(1009);
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(ID, CONTENT);
        eq(game.getEpisode(ID).challengeDeadline, 1029);
        vm.warp(1028);
        vm.prank(CHALLENGER);
        game.challenge{value: 1000}(ID, EVIDENCE);
        eq(game.getEpisode(ID).commitDeadline, 1058);
        eq(game.getEpisode(ID).revealDeadline, 1098);
        vm.warp(1057);
        commit(0, 0);
        vm.warp(1058);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.Reveal));
        vm.warp(1097);
        reveal(0, 0);
        vm.warp(1098);
        game.settle(ID);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.Aborted));
    }

    function test_reveal_rejects_wrong_nonzero_assessment_and_copied_juror_preimage() public {
        challenged(1000, 3);
        bytes32 commitment = game.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT);
        vm.prank(juror(0));
        game.commitVote{value: 100}(ID, commitment);
        vm.prank(juror(1));
        game.commitVote{value: 100}(ID, commitment);
        beginReveal();
        vm.prank(juror(0));
        vm.expectRevert(Veracity.InvalidCommitment.selector);
        game.revealVote(ID, 0, keccak256("different assessment"), SALT);
        vm.prank(juror(1));
        vm.expectRevert(Veracity.InvalidCommitment.selector);
        game.revealVote(ID, 0, ASSESSMENT, SALT);
        truth(!game.getJuror(ID, juror(0)).revealed);
        truth(!game.getJuror(ID, juror(1)).revealed);
        eq(game.getEpisode(ID).creatorVotes, 0);
        reveal(0, 0);
        eq(game.getEpisode(ID).creatorVotes, 1);
    }

    function test_commit_rejects_overpayment_without_recording_or_locking_it() public {
        challenged(1000, 3);
        bytes32 commitment = game.commitmentFor(ID, juror(0), 0, ASSESSMENT, SALT);
        vm.prank(juror(0));
        vm.expectRevert(Veracity.IncorrectDeposit.selector);
        game.commitVote{value: 101}(ID, commitment);
        eq(game.getJuror(ID, juror(0)).commitment, bytes32(0));
        eq(game.getEpisode(ID).totalDeposited, 2000);
        eq(game.totalLocked(), 2000);
        eq(address(game).balance, 2000);
        commit(0, 0);
        eq(game.totalLocked(), 2100);
    }

    function test_expire_rejects_a_challenged_episode_before_and_after_deadlines() public {
        challenged(1000, 3);
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.expire(ID);
        finishReveal();
        vm.expectRevert(Veracity.WrongPhase.selector);
        game.expire(ID);
        eq(game.totalLocked(), 2000);
        game.settle(ID);
        eq(uint256(game.phase(ID)), uint256(Veracity.State.Aborted));
        eq(game.credits(CREATOR), 1000);
        eq(game.credits(CHALLENGER), 1000);
    }

    function test_event_ledger_reconstructs_resolved_deposits_rewards_and_forfeitures() public {
        vm.recordLogs();
        challenged(107, 5);
        for (uint256 i; i < 5; i++) {
            commit(i, 1);
        }
        beginReveal();
        for (uint256 i; i < 3; i++) {
            reveal(i, 1);
        }
        finishReveal();
        game.settle(ID);
        assertEventLedger(vm.getRecordedLogs());
        eq(game.getSettlement(ID).protocolFee, 12);
        eq(game.getSettlement(ID).forfeitedBonds, 20);
    }

    function test_event_ledger_reconstructs_abort_refunds_and_forfeitures() public {
        vm.recordLogs();
        challenged(1000, 5);
        for (uint256 i; i < 5; i++) {
            commit(i, 0);
        }
        beginReveal();
        reveal(0, 0);
        reveal(1, 0);
        finishReveal();
        game.settle(ID);
        assertEventLedger(vm.getRecordedLogs());
        eq(game.getSettlement(ID).protocolFee, 0);
        eq(game.getSettlement(ID).forfeitedBonds, 300);
    }

    function test_event_ledger_reconstructs_unchallenged_refund_without_fee() public {
        vm.recordLogs();
        register(1000, 5);
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.warp(game.getEpisode(ID).challengeDeadline);
        game.expire(ID);
        assertEventLedger(vm.getRecordedLogs());
        eq(game.credits(CREATOR), 1000);
        eq(game.credits(TREASURY), 0);
    }

    function test_event_ledger_reconstructs_unfunded_expiry_without_credits() public {
        vm.recordLogs();
        register(1000, 5);
        vm.warp(game.getEpisode(ID).postingDeadline);
        game.expire(ID);
        assertEventLedger(vm.getRecordedLogs());
        eq(game.totalDeposited(), 0);
        eq(game.totalCredits(), 0);
    }

    function assertEventLedger(Vm.Log[] memory logs) internal view {
        Veracity.EpisodeView memory episode = game.getEpisode(ID);
        Veracity.Settlement memory result = game.getSettlement(ID);
        address[] memory recipients = new address[](episode.config.jurors.length + 3);
        uint256[] memory observedCredits = new uint256[](recipients.length);
        recipients[0] = CREATOR;
        recipients[1] = CHALLENGER;
        recipients[2] = TREASURY;
        for (uint256 i; i < episode.config.jurors.length; i++) {
            recipients[i + 3] = juror(i);
        }
        uint256 observedDeposits;
        uint256 observedTotalCredits;
        uint256 observedForfeits;
        uint256 terminalTransitions;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].emitter != address(game)) continue;
            eq(logs[i].topics[1], ID);
            bytes32 signature = logs[i].topics[0];
            if (signature == Veracity.ClaimPosted.selector) {
                (, uint256 amount,) = abi.decode(logs[i].data, (bytes32, uint256, uint64));
                observedDeposits += amount;
            } else if (signature == Veracity.Challenged.selector) {
                (, uint256 amount,,) = abi.decode(logs[i].data, (bytes32, uint256, uint64, uint64));
                observedDeposits += amount;
            } else if (signature == Veracity.VoteCommitted.selector) {
                (, uint256 amount) = abi.decode(logs[i].data, (bytes32, uint256));
                observedDeposits += amount;
            } else if (signature == Veracity.CreditAccrued.selector) {
                uint256 amount = abi.decode(logs[i].data, (uint256));
                address recipient = address(uint160(uint256(logs[i].topics[2])));
                bool knownRecipient;
                for (uint256 slot; slot < recipients.length; slot++) {
                    if (recipient == recipients[slot]) {
                        observedCredits[slot] += amount;
                        knownRecipient = true;
                        break;
                    }
                }
                truth(knownRecipient);
                observedTotalCredits += amount;
            } else if (signature == Veracity.JurorForfeited.selector) {
                observedForfeits += abi.decode(logs[i].data, (uint256));
            } else if (signature == Veracity.EpisodeSettled.selector) {
                (Veracity.State outcome, address winner,,) =
                    abi.decode(logs[i].data, (Veracity.State, address, uint8, uint8));
                eq(uint256(outcome), uint256(result.outcome));
                eq(winner, result.winner);
                terminalTransitions++;
            } else if (signature == Veracity.EpisodeExpired.selector) {
                eq(uint256(abi.decode(logs[i].data, (Veracity.State))), uint256(result.outcome));
                terminalTransitions++;
            }
        }
        eq(terminalTransitions, 1);
        eq(observedDeposits, episode.totalDeposited);
        eq(observedDeposits, observedTotalCredits);
        eq(observedForfeits, result.forfeitedBonds);
        eq(observedCredits[2], result.protocolFee + result.forfeitedBonds);
        for (uint256 i; i < recipients.length; i++) {
            eq(observedCredits[i], game.entitlement(ID, recipients[i]));
        }
    }

    function test_multi_episode_credits_withdraw_together_without_spending_locked_escrow() public {
        bytes32 second = keccak256("second episode");
        bytes32 third = keccak256("third episode");
        register(1000, 3);
        game.registerEpisode(second, config(1000, 3));
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(ID, CONTENT);
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(second, CONTENT);
        vm.warp(1005);
        game.registerEpisode(third, config(1000, 3));
        vm.prank(CREATOR);
        game.postClaim{value: 1000}(third, CONTENT);
        vm.warp(1020);
        game.expire(ID);
        game.expire(second);
        eq(game.credits(CREATOR), 2000);
        eq(game.totalLocked(), 1000);
        uint256 initialBalance = CREATOR.balance;
        vm.prank(CREATOR);
        game.withdraw();
        eq(CREATOR.balance, initialBalance + 2000);
        eq(game.totalWithdrawn(), 2000);
        eq(game.totalCredits(), 0);
        eq(game.totalLocked(), 1000);
        eq(address(game).balance, 1000);
        eq(uint256(game.phase(third)), uint256(Veracity.State.Open));
        eq(game.entitlement(ID, CREATOR), 1000);
        eq(game.entitlement(second, CREATOR), 1000);
        eq(game.entitlement(third, CREATOR), 0);
        vm.warp(1025);
        game.expire(third);
        vm.prank(CREATOR);
        game.withdraw();
        eq(game.totalWithdrawn(), 3000);
        eq(game.totalDeposited(), 3000);
        eq(game.totalCredits(), 0);
        eq(game.totalLocked(), 0);
        eq(address(game).balance, 0);
    }
}
