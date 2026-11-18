// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Veracity} from "../src/Veracity.sol";
import {Vm} from "./Veracity.t.sol";

contract EpisodeHandler {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 public constant ID = keccak256("stateful episode");
    bytes32 private constant HASH = keccak256("artifact");
    bytes32 private constant SALT = keccak256("stateful test secret");
    address private constant CREATOR = address(0xC0);
    address private constant CHALLENGER = address(0xC1);
    address private constant TREASURY = address(0xF0);
    Veracity public game;
    mapping(uint256 => uint8) private committedVerdict;

    constructor() {
        vm.warp(1000);
        vm.deal(address(this), 100 ether);
        vm.deal(CREATOR, 100 ether);
        vm.deal(CHALLENGER, 100 ether);
        game = new Veracity(address(this));
        address[] memory jurors = new address[](5);
        for (uint256 i; i < 5; i++) {
            jurors[i] = address(uint160(0x100 + i));
            vm.deal(jurors[i], 100 ether);
        }
        game.registerEpisode(
            ID,
            Veracity.Config({
                creator: CREATOR,
                challenger: CHALLENGER,
                jurors: jurors,
                treasury: TREASURY,
                configurationHash: HASH,
                beta: 1000,
                gammaBps: 1000,
                winnerBps: 6000,
                jurorBps: 3000,
                protocolBps: 1000,
                postingDuration: 10,
                challengeDuration: 10,
                commitDuration: 10,
                revealDuration: 10
            })
        );
    }

    function post() external {
        vm.prank(CREATOR);
        try game.postClaim{value: 1000}(ID, HASH) {} catch {}
    }

    function challenge() external {
        vm.prank(CHALLENGER);
        try game.challenge{value: 1000}(ID, HASH) {} catch {}
    }

    function commit(uint8 jurorSeed, uint8 verdictSeed) external {
        uint256 index = uint256(jurorSeed) % 5;
        address juror = address(uint160(0x100 + index));
        uint8 verdict = verdictSeed % 2;
        bytes32 commitment = game.commitmentFor(ID, juror, verdict, HASH, SALT);
        vm.prank(juror);
        try game.commitVote{value: 100}(ID, commitment) {
            committedVerdict[index] = verdict;
        } catch {}
    }

    function reveal(uint8 jurorSeed) external {
        uint256 index = uint256(jurorSeed) % 5;
        vm.prank(address(uint160(0x100 + index)));
        try game.revealVote(ID, committedVerdict[index], HASH, SALT) {} catch {}
    }

    function advance(uint8 secondsSeed) external {
        vm.warp(block.timestamp + uint256(secondsSeed) % 11);
    }

    function settle() external {
        try game.settle(ID) {} catch {}
    }

    function expire() external {
        try game.expire(ID) {} catch {}
    }

    function withdraw(uint8 participantSeed) external {
        vm.prank(participant(participantSeed));
        try game.withdraw() {} catch {}
    }

    function transfer(uint8 senderSeed, uint8 recipientSeed, uint256 amountSeed) external {
        address sender = participant(senderSeed);
        uint256 available = game.credits(sender);
        vm.prank(sender);
        try game.transferCredits(participant(recipientSeed), available == 0 ? 0 : amountSeed % (available + 1)) {}
            catch {}
    }

    function participant(uint8 seed) private pure returns (address) {
        uint256 slot = uint256(seed) % 8;
        return slot == 0 ? CREATOR : slot == 1 ? CHALLENGER : slot == 2 ? TREASURY : address(uint160(0x100 + slot - 3));
    }

    function sumCredits() external view returns (uint256 sum) {
        sum = game.credits(CREATOR) + game.credits(CHALLENGER) + game.credits(TREASURY);
        for (uint256 i; i < 5; i++) {
            sum += game.credits(address(uint160(0x100 + i)));
        }
    }
}

contract VeracityInvariantTest {
    EpisodeHandler private handler;

    function setUp() public {
        handler = new EpisodeHandler();
    }

    function targetContracts() public view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(handler);
    }

    function invariant_deposits_equal_locked_credits_and_withdrawn() public view {
        Veracity game = handler.game();
        require(
            game.totalDeposited() == game.totalLocked() + game.totalCredits() + game.totalWithdrawn(),
            "deposit conservation"
        );
        require(handler.sumCredits() == game.totalCredits(), "credit accounting");
    }

    function invariant_contract_balance_covers_all_outstanding_liabilities() public view {
        Veracity game = handler.game();
        require(address(game).balance >= game.totalLocked() + game.totalCredits(), "insolvent contract");
    }

    function invariant_episode_liability_or_historical_entitlements_equal_deposits() public view {
        Veracity game = handler.game();
        Veracity.EpisodeView memory episode = game.getEpisode(handler.ID());
        require(episode.totalDeposited == episode.lockedLiability + episode.totalCredited, "episode accounting");
    }
}
